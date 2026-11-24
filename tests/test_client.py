import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from conftest import (
    MARKER_KEY,
    TASK_ID,
    TASKS_URL,
    VIDEO_URL,
    created_reply,
    error_reply,
    journal_events,
    read_journal,
    success_reply,
    task_reply,
)

from seedance_client import errors
from seedance_client.catalog import ServiceTier
from seedance_client.client import OverwritePolicy, SeedanceClient
from seedance_client.validation import VideoRequest

IMAGE = "https://example.com/cat.png"
TEXT = VideoRequest("seedance-1-0-pro-250528", "480p", "16:9", 5, prompt="A cat")
REFUSE = OverwritePolicy.REFUSE
REPLACE = OverwritePolicy.REPLACE

# --- Create ---


@pytest.mark.parametrize(
    ("request_", "extra"),
    [
        (TEXT, {"content": [{"type": "text", "text": "A cat"}]}),
        (
            replace(TEXT, image_url=IMAGE),
            {
                "content": [
                    {"type": "text", "text": "A cat"},
                    {"type": "image_url", "image_url": {"url": IMAGE}, "role": "first_frame"},
                ]
            },
        ),
        (
            replace(TEXT, image_url=IMAGE, prompt=None),
            {
                "content": [
                    {"type": "image_url", "image_url": {"url": IMAGE}, "role": "first_frame"}
                ]
            },
        ),
        (
            replace(TEXT, service_tier=ServiceTier.FLEX),
            {"content": [{"type": "text", "text": "A cat"}], "service_tier": "flex"},
        ),
    ],
)
def test_create_sends_exact_body(client, api, request_, extra):
    api.replies = [created_reply()]
    assert client.create(request_) == TASK_ID
    sent = api.requests[0]
    assert (sent.method, str(sent.url)) == ("POST", TASKS_URL)
    assert sent.headers["Authorization"] == f"Bearer {MARKER_KEY}"
    assert json.loads(sent.content) == {
        "model": "seedance-1-0-pro-250528",
        "resolution": "480p",
        "ratio": "16:9",
        "duration": 5,
        **extra,
    }


def test_create_journal(client, api):
    api.replies = [created_reply()]
    client.create(replace(TEXT, image_url=IMAGE))
    opened, created = read_journal()
    assert (opened["event"], created["event"]) == ("submitting", "created")
    assert opened["attempt"] == created["attempt"]
    fields = ("model", "resolution", "ratio", "duration", "tier", "mode", "prompt")
    assert [opened[name] for name in fields] == [
        TEXT.model,
        "480p",
        "16:9",
        5,
        "default",
        "image",
        "A cat",
    ]
    assert created["task_id"] == TASK_ID
    assert created["estimate_usd"] == {"low": "0.1215", "high": "0.1215"}


def test_submitting_before_post(client, api, monkeypatch):
    seen = []
    api.replies = [created_reply()]
    original = type(api).__call__

    def spy(self, request):
        seen.extend(journal_events())
        return original(self, request)

    monkeypatch.setattr(type(api), "__call__", spy)
    client.create(TEXT)
    assert seen == ["submitting"]


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "AuthenticationError", errors.AuthError),
        (403, "AccountOverdueError", errors.AccountError),
        (404, "ModelNotOpen", errors.ModelAccessError),
        (400, "InvalidParameter.X", errors.InvalidInputError),
        (400, "InputTextSensitiveContentDetected", errors.ContentRejectedError),
        (429, "ModelAccountRpmRateLimitExceeded", errors.RateLimitError),
        (429, "SetLimitExceeded", errors.QuotaError),
    ],
)
def test_create_refused_by_api(client, api, clock, status, code, expected):
    api.replies = [error_reply(status, code)]
    with pytest.raises(expected):
        client.create(TEXT)
    assert len(api.requests) == 1
    assert clock.sleeps == []
    rejected = read_journal()[-1]
    assert rejected["event"] == "rejected"
    assert (rejected["code"], rejected["http_status"]) == (code, status)
    assert rejected["request_id"] == "req-1"


@pytest.mark.parametrize("fault", [httpx.ConnectError("x"), httpx.ConnectTimeout("x")])
def test_create_never_connected(client, api, clock, fault):
    api.replies = [fault]
    with pytest.raises(errors.NetworkError, match="Nothing was sent"):
        client.create(TEXT)
    assert len(api.requests) == 1
    assert clock.sleeps == []
    assert journal_events() == ["submitting", "rejected"]


@pytest.mark.parametrize(
    "fault",
    [
        httpx.ReadTimeout("x"),
        httpx.WriteTimeout("x"),
        httpx.ReadError("x"),
        httpx.RemoteProtocolError("x"),
        error_reply(500, "InternalServiceError"),
        error_reply(503, "ServerOverloaded"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"id": ""}),
        httpx.Response(200, json={"id": 5}),
        httpx.Response(200, text="<html>"),
        httpx.Response(302, headers={"Location": "https://evil.example.com"}),
        httpx.Response(400, text="<html>"),
        httpx.Response(400, json={"error": {}}),
    ],
)
def test_create_outcome_unknown(client, api, clock, fault):
    api.replies = [fault]
    with pytest.raises(errors.CreateOutcomeUnknown) as caught:
        client.create(TEXT)
    assert "task list" in caught.value.next_step
    assert len(api.requests) == 1
    assert clock.sleeps == []
    assert journal_events() == ["submitting", "unknown"]

    # The open attempt stops the next create.
    with pytest.raises(errors.OpenAttemptError):
        client.create(TEXT)
    assert len(api.requests) == 1


def test_killed_create_stays_open(client, api):
    api.replies = [KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):
        client.create(TEXT)
    assert journal_events() == ["submitting"]
    with pytest.raises(errors.OpenAttemptError):
        client.create(TEXT)


def test_resolve_allows_create(client, api):
    api.replies = [httpx.ReadTimeout("x"), created_reply()]
    with pytest.raises(errors.CreateOutcomeUnknown):
        client.create(TEXT)
    client.resolve_attempts()
    assert client.create(TEXT) == TASK_ID
    assert journal_events() == ["submitting", "unknown", "resolved", "submitting", "created"]


@pytest.mark.parametrize("change", [{"duration": 99}, {"prompt": None}, {"resolution": "8k"}])
def test_bad_request_not_sent(client, api, change):
    with pytest.raises(errors.InvalidInputError):
        client.create(replace(TEXT, **change))
    assert api.requests == []
    assert journal_events() == []


@pytest.mark.parametrize("key", [None, "", "  ", "bad\nkey", "clé"])
def test_bad_key_sends_nothing(client, api, monkeypatch, key):
    monkeypatch.delenv("ARK_API_KEY")
    if key is not None:
        monkeypatch.setenv("ARK_API_KEY", key)
    with pytest.raises(errors.MissingKeyError, match="ARK_API_KEY"):
        client.create(TEXT)
    assert api.requests == []
    assert journal_events() == []


def test_unsaved_task_id_is_shown(client, api, monkeypatch):
    api.replies = [created_reply()]
    journal = client._journal
    original = journal.append

    def full_disk(event, **fields):
        if event == "created":
            raise errors.JournalError("Disk full.")
        original(event, **fields)

    monkeypatch.setattr(journal, "append", full_disk)
    with pytest.raises(errors.JournalError, match=TASK_ID):
        client.create(TEXT)


def test_unknown_journal_fails(client, api, monkeypatch):
    api.replies = [error_reply(500, "InternalServiceError")]
    original = client._journal.append

    def full_disk(event, **fields):
        if event == "unknown":
            raise errors.JournalError("Disk full.")
        original(event, **fields)

    monkeypatch.setattr(client._journal, "append", full_disk)
    with pytest.raises(errors.CreateOutcomeUnknown, match="may or may not.*Disk full") as caught:
        client.create(TEXT)
    assert caught.value.request_id == "req-1"
    assert caught.value.status == 500
    with pytest.raises(errors.OpenAttemptError):
        client.check_open_attempts()


# --- Wait ---


def test_wait_until_success(client, api, clock):
    api.replies = [task_reply("queued"), task_reply("running"), success_reply()]
    seen = []
    task = client.wait(TASK_ID, on_poll=lambda task: seen.append(task.status))
    assert seen == ["queued", "running", "succeeded"]
    assert task.tokens == 48600
    assert clock.sleeps == [5, 7.5]
    finished = read_journal()[-1]
    del finished["ts"]
    assert finished == {
        "event": "finished",
        "task_id": TASK_ID,
        "status": "succeeded",
        "tokens": 48600,
        "cost_usd": "0.1215",
    }


def test_poll_delay_grows(client, api, clock):
    api.replies = [task_reply("running")] * 7 + [success_reply()]
    client.wait(TASK_ID)
    assert clock.sleeps == [5, 7.5, 11.25, 16.875, 25.3125, 30, 30]


@pytest.mark.parametrize(
    "fault",
    [error_reply(429, "ServerOverloaded"), error_reply(502, None), httpx.ConnectError("x")],
)
def test_wait_survives_faults(client, api, clock, fault):
    api.replies = [task_reply("queued"), fault, success_reply()]
    client.wait(TASK_ID)
    assert clock.sleeps == [5, 1]


def test_wait_retries_exhausted(client, api):
    api.replies = [task_reply("queued")] + [error_reply(500, "InternalServiceError")] * 5
    with pytest.raises(errors.ServerError):
        client.wait(TASK_ID)
    assert len(api.requests) == 6


@pytest.mark.parametrize("status", ["failed", "expired", "cancelled"])
def test_wait_reports_failed_task(client, api, status):
    error = {"code": "InvalidParameter.TaskTypeMismatch", "message": "Wrong type."}
    api.replies = [task_reply(status, error=error)]
    with pytest.raises(errors.TaskFailedError) as caught:
        client.wait(TASK_ID)
    assert caught.value.task_status == status
    assert caught.value.code == "InvalidParameter.TaskTypeMismatch"
    assert "Wrong type." in str(caught.value)
    assert read_journal()[-1]["status"] == status
    assert read_journal()[-1]["cost_usd"] is None


def test_failed_task_no_details(client, api):
    api.replies = [task_reply("failed", error=None, content=None, usage=None)]
    with pytest.raises(errors.TaskFailedError):
        client.wait(TASK_ID)


def test_wait_timeout(client, api, clock):
    api.replies = [task_reply("running")] * 4
    with pytest.raises(errors.WaitTimeoutError, match="keeps running") as caught:
        client.wait(TASK_ID, timeout=20)
    assert "seedance wait" in caught.value.next_step
    assert clock.sleeps == [5, 7.5, 7.5]


def test_retry_sleep_is_capped(client, api, clock):
    fault = error_reply(429, "ServerOverloaded", headers={"Retry-After": "60"})
    api.replies = [fault] * 3
    with pytest.raises(errors.WaitTimeoutError, match="could not be read") as caught:
        client.wait(TASK_ID, timeout=10)
    assert clock.sleeps == [10]
    assert len(api.requests) == 2
    assert caught.value.request_id == "req-1"


def test_retry_at_deadline(client, api, clock):
    fault = error_reply(429, "ServerOverloaded", headers={"Retry-After": "60"})
    api.replies = [task_reply("running"), fault, success_reply()]
    assert client.wait(TASK_ID, timeout=10).status == "succeeded"
    assert clock.sleeps == [5, 5]


def test_unknown_status_polls(client, api):
    api.replies = [task_reply("rendering"), success_reply()]
    assert client.wait(TASK_ID).status == "succeeded"


def test_resume_after_interrupt(make_client, api, clock):
    first = make_client()
    api.replies = [created_reply(), task_reply("queued")]
    first.create(TEXT)

    def interrupt(_seconds):
        raise KeyboardInterrupt

    stopped = SeedanceClient(interrupt, clock.now, http=httpx.MockTransport(api))
    with pytest.raises(KeyboardInterrupt):
        stopped.wait(stopped.resolve_task_id(None))

    # A new run with no ID finds the same task and sends no POST.
    again = make_client()
    api.replies = [success_reply()]
    assert again.wait(again.resolve_task_id(None)).task_id == TASK_ID
    assert str(api.requests[-1].url) == f"{TASKS_URL}/{TASK_ID}"
    assert api.count("POST") == 1


def test_no_task_id_anywhere(client):
    with pytest.raises(errors.NoTaskError):
        client.resolve_task_id(None)


@pytest.mark.parametrize("field", ["model", "resolution", "service_tier", "usage"])
def test_cost_needs_all_data(client, api, field):
    body = json.loads(success_reply().content)
    del body[field]
    api.replies = [httpx.Response(200, json=body)]
    assert client.list_cost(client.get_task(TASK_ID)) is None


# --- Download ---


def test_download_writes_file(client, api):
    api.replies = [success_reply(), httpx.Response(200, content=b"video")]
    path = client.download(TASK_ID, None, REFUSE)
    assert path == Path("outputs") / f"{TASK_ID}.mp4"
    assert path.read_bytes() == b"video"
    assert list(path.parent.iterdir()) == [path]

    # The storage host must never get the key.
    assert str(api.requests[1].url) == VIDEO_URL
    assert "Authorization" not in api.requests[1].headers


@pytest.mark.parametrize("status", [403, 404])
def test_download_link_expired(client, api, status):
    api.replies = [success_reply(), httpx.Response(status)]
    with pytest.raises(errors.OutputUrlExpiredError, match="24 hours"):
        client.download(TASK_ID, Path("a.mp4"), REFUSE)
    assert not Path("a.mp4").exists()


def test_download_retries(client, api, clock):
    api.replies = [success_reply(), httpx.ReadError("x"), httpx.Response(500)]
    api.replies.append(httpx.Response(200, content=b"video"))
    client.download(TASK_ID, Path("a.mp4"), REFUSE)
    assert Path("a.mp4").read_bytes() == b"video"
    assert clock.sleeps == [1, 2]


def test_download_gives_up(client, api):
    api.replies = [success_reply()] + [httpx.ReadError("x")] * 3
    with pytest.raises(errors.NetworkError) as caught:
        client.download(TASK_ID, Path("a.mp4"), REFUSE)
    assert "signature" not in str(caught.value)
    assert not Path("a.mp4").exists()


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (task_reply("running"), errors.TaskNotReadyError),
        (task_reply("succeeded"), errors.TaskNotReadyError),
        (task_reply("failed"), errors.TaskFailedError),
    ],
)
def test_download_needs_success(client, api, reply, expected):
    api.replies = [reply]
    with pytest.raises(expected):
        client.download(TASK_ID, None, REFUSE)


def test_download_keeps_old_file(client, api):
    Path("a.mp4").write_bytes(b"old")
    with pytest.raises(errors.OutputFileError, match="already exists"):
        client.download(TASK_ID, Path("a.mp4"), REFUSE)
    assert api.requests == []

    api.replies = [success_reply(), httpx.Response(200, content=b"new")]
    client.download(TASK_ID, Path("a.mp4"), REPLACE)
    assert Path("a.mp4").read_bytes() == b"new"


def test_download_bad_path(client, api):
    Path("file").write_text("x")
    api.replies = [success_reply()]
    with pytest.raises(errors.OutputFileError):
        client.download(TASK_ID, Path("file/a.mp4"), REFUSE)
