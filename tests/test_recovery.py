"""What the user is told when a paid request may exist."""

from dataclasses import replace

import httpx
import pytest
from conftest import TASK_ID, created_reply, error_reply, task_reply

from seedance_client import cli, errors
from seedance_client.catalog import ServiceTier
from seedance_client.validation import VideoRequest

ONLINE = VideoRequest("seedance-1-0-pro-250528", "480p", "16:9", 5, prompt="A cat")
FLEX = replace(ONLINE, service_tier=ServiceTier.FLEX)
ONLINE_FILTER = "filter.service_tier=default"
FLEX_FILTER = "filter.service_tier=flex"


@pytest.fixture
def break_journal(client, monkeypatch):
    """Makes one journal event fail with the given exception."""
    original = client._journal.append

    def install(bad_event, fault):
        def append(event, **fields):
            if event == bad_event:
                raise fault
            original(event, **fields)

        monkeypatch.setattr(client._journal, "append", append)

    return install


@pytest.mark.parametrize(
    ("request_", "shown", "hidden"),
    [(ONLINE, ONLINE_FILTER, FLEX_FILTER), (FLEX, FLEX_FILTER, ONLINE_FILTER)],
)
def test_advice_names_the_tier(client, api, request_, shown, hidden):
    api.replies = [httpx.ReadTimeout("x")]
    with pytest.raises(errors.CreateOutcomeUnknown) as unknown:
        client.create(request_)
    with pytest.raises(errors.OpenAttemptError) as blocked:
        client.create(request_)

    for error in (unknown.value, blocked.value):
        assert shown in error.next_step
        assert hidden not in error.next_step
        assert "both tiers" in error.next_step
        assert "page_num" in error.next_step
        assert "page_size" not in error.next_step
        assert "Set ARK_API_KEY in this shell first" in error.next_step


def test_advice_mixed_tiers(client):
    client._journal.append("submitting", attempt="a", tier="default")
    client._journal.append("submitting", attempt="b", tier="flex")
    with pytest.raises(errors.OpenAttemptError) as caught:
        client.check_open_attempts()
    assert ONLINE_FILTER in caught.value.next_step
    assert FLEX_FILTER in caught.value.next_step


def test_advice_for_missing_tier(client):
    client._journal.append("submitting", attempt="a")
    with pytest.raises(errors.OpenAttemptError) as caught:
        client.check_open_attempts()
    assert ONLINE_FILTER in caught.value.next_step
    assert FLEX_FILTER in caught.value.next_step


def test_refusal_survives_journal(client, api, break_journal):
    break_journal("rejected", errors.JournalError("Disk full."))
    api.replies = [error_reply(404, "ModelNotOpen", "Model is not open.")]
    with pytest.raises(errors.ModelAccessError, match="not open.*Disk full") as caught:
        client.create(ONLINE)
    assert caught.value.code == "ModelNotOpen"
    assert caught.value.request_id == "req-1"


def test_interrupt_holds_id(client, api, break_journal, capsys):
    break_journal("created", KeyboardInterrupt())
    api.replies = [created_reply()]
    with pytest.raises(errors.CreateInterrupted) as caught:
        client.create(ONLINE)
    assert caught.value.task_id == TASK_ID

    # The domain layer prints nothing, and the attempt stays open.
    shown = capsys.readouterr()
    assert shown.out + shown.err == ""
    with pytest.raises(errors.OpenAttemptError):
        client.check_open_attempts()


def test_interrupt_shows_task_id(client, api, break_journal, capsys):
    break_journal("created", KeyboardInterrupt())
    api.replies = [created_reply()]
    argv = ["create", "--model", ONLINE.model, "--resolution", "480p", "--ratio", "16:9"]
    argv += ["--duration", "5", "--prompt", "A cat", "--yes"]
    assert cli.main(argv, lambda: client) == errors.ExitCode.INTERRUPTED
    assert TASK_ID in capsys.readouterr().err


def test_unread_task_message(client, api):
    api.replies = [task_reply("running")] + [httpx.ReadError("x")] * 5
    with pytest.raises(errors.WaitTimeoutError) as caught:
        client.wait(TASK_ID, timeout=6)
    assert "could not be read" in str(caught.value)
    assert "keeps running" not in str(caught.value)


def test_billing_text_is_exact(client, api, capsys):
    reply = task_reply("succeeded", usage={"completion_tokens": 48600})
    api.replies = [reply]
    assert cli.main(["status", TASK_ID], lambda: client) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "cannot show the billed amount" in out
    assert "Billing overview shows the account balance" in out
    assert "Usage statistics shows token usage" in out
