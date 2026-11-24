import httpx
import pytest
from conftest import MARKER_KEY, TASK_ID, TASKS_URL, error_reply, task_reply

from seedance_client import errors

READ_ERROR = httpx.ReadTimeout("slow")


def test_get_sends_key_to_api(client, api):
    api.replies = [task_reply("queued")]
    assert client.get_task(TASK_ID).status == "queued"
    request = api.requests[0]
    assert str(request.url) == f"{TASKS_URL}/{TASK_ID}"
    assert request.headers["Authorization"] == f"Bearer {MARKER_KEY}"


@pytest.mark.parametrize(
    "fault",
    [error_reply(429, "ServerOverloaded"), error_reply(500, "InternalServiceError"), READ_ERROR],
)
def test_reads_retry(client, api, clock, fault):
    api.replies = [fault, fault, task_reply("queued")]
    client.get_task(TASK_ID)
    assert clock.sleeps == [1, 2]


def test_reads_stop_after_five(client, api, clock):
    api.replies = [READ_ERROR] * 5
    with pytest.raises(errors.NetworkError):
        client.get_task(TASK_ID)
    assert clock.sleeps == [1, 2, 4, 8]
    assert len(api.requests) == 5


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "AuthenticationError", errors.AuthError),
        (429, "SetLimitExceeded", errors.QuotaError),
        (404, "NotFound.Task", errors.TaskNotFoundError),
        (404, None, errors.TaskNotFoundError),
        (404, "ModelNotOpen", errors.ModelAccessError),
        (302, None, errors.ApiError),
    ],
)
def test_other_reads_do_not_retry(client, api, clock, status, code, expected):
    api.replies = [error_reply(status, code)]
    with pytest.raises(expected) as caught:
        client.get_task(TASK_ID)
    assert type(caught.value) is expected
    assert clock.sleeps == []


@pytest.mark.parametrize(
    ("header", "sleep"), [("7", 7), ("0", 0), ("999", 60), ("soon", 1), ("-5", 1), ("nan", 1)]
)
def test_retry_after_header(client, api, clock, header, sleep):
    fault = error_reply(429, "ServerOverloaded", headers={"Retry-After": header})
    api.replies = [fault, task_reply("queued")]
    client.get_task(TASK_ID)
    assert clock.sleeps == [sleep]


def test_error_carries_details(client, api):
    # The x-error-code header must be ignored.
    headers = {"x-error-code": "AuthN_AuthenticationError"}
    api.replies = [error_reply(401, "AuthenticationError", "Bad key.", headers)]
    with pytest.raises(errors.AuthError) as caught:
        client.get_task(TASK_ID)
    error = caught.value
    assert (error.status, error.code, str(error)) == (401, "AuthenticationError", "Bad key.")
    assert error.request_id == "req-1"


def test_request_id_from_message(client, api):
    message = "The API key format is incorrect. Request id: 0217abc"
    body = {"error": {"code": "AuthenticationError", "message": message}}
    api.replies = [httpx.Response(401, json=body)]
    with pytest.raises(errors.AuthError) as caught:
        client.get_task(TASK_ID)
    assert caught.value.request_id == "0217abc"


def test_bad_json_on_read_retries(client, api, clock):
    api.replies = [httpx.Response(200, text="<html>"), task_reply("queued")]
    client.get_task(TASK_ID)
    assert clock.sleeps == [1]


def test_redirect_is_not_followed(client, api):
    api.replies = [httpx.Response(302, headers={"Location": "https://evil.example.com"})]
    with pytest.raises(errors.ApiError):
        client.get_task(TASK_ID)
    assert len(api.requests) == 1


def test_task_id_is_quoted(client, api):
    api.replies = [error_reply(404, "NotFound.Task")]
    with pytest.raises(errors.TaskNotFoundError):
        client.get_task("a/b?c")
    assert api.requests[0].url.raw_path.endswith(b"/tasks/a%2Fb%3Fc")
