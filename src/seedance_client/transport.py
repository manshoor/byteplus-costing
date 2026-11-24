"""Driver layer: raw HTTP. Create is sent once. Only reads are retried."""

import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import httpx

from seedance_client.errors import (
    HTTP_BAD_REQUEST,
    HTTP_FORBIDDEN,
    HTTP_NOT_FOUND,
    HTTP_SERVER_ERROR,
    ApiError,
    CreateOutcomeUnknown,
    NetworkError,
    OutputFileError,
    OutputUrlExpiredError,
    SeedanceError,
    ServerError,
    TaskNotFoundError,
    classify_error,
)

_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"

_CLIENT_ERRORS = range(HTTP_BAD_REQUEST, HTTP_SERVER_ERROR)
_REQUEST_ID_HEADER = "x-request-id"
_REQUEST_ID_TEXT = re.compile(r"Request id: (\w+)", re.IGNORECASE)

# Our choices, not from the docs.
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 30.0
_CREATE_READ_TIMEOUT = 60.0
_READ_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0)
_DOWNLOAD_RETRY_DELAYS = (1.0, 2.0)
_RETRY_AFTER_CAP = 60.0

_HIDDEN_KEY = "[key hidden]"


class Transport:
    """Two HTTP clients: one with the key for the API, one without it for storage."""

    def __init__(
        self,
        api_key: str,
        sleep: Callable[[float], None],
        http: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._sleep = sleep
        timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)

        # No redirects here: the key must reach the API host only.
        self._api = httpx.Client(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            follow_redirects=False,
            transport=http,
        )
        self._storage = httpx.Client(timeout=timeout, follow_redirects=False, transport=http)

    def close(self) -> None:
        """Close both clients."""
        self._api.close()
        self._storage.close()

    def post_once(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Send one POST. Never retried: a second send can make a second paid video."""
        timeout = httpx.Timeout(_CREATE_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
        try:
            response = self._api.post(path, json=body, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as error:
            raise NetworkError(
                "Could not connect. Nothing was sent, so it is safe to run this again."
            ) from error
        except httpx.HTTPError as error:
            raise CreateOutcomeUnknown(
                f"The connection failed after sending ({type(error).__name__}). "
                "The task may or may not exist."
            ) from error

        parsed = self._parse(response)

        # Our assumption: a 4xx with an error code means that no task was made.
        if response.status_code in _CLIENT_ERRORS and _error_text(parsed, "code"):
            _raise_api_error(response, parsed)
        if not response.is_success or not isinstance(parsed, dict):
            _raise_unknown(response, parsed, f"unclear answer, HTTP {response.status_code}")
        if not isinstance(parsed.get("id"), str) or not parsed["id"]:
            _raise_unknown(response, parsed, "answer without a task ID")
        return parsed

    def get_json(
        self, path: str, time_left: Callable[[], float] = lambda: math.inf
    ) -> dict[str, Any]:
        """Read one JSON object. Retry while time is left."""
        return self._with_retries(lambda: self._get_once(path), _READ_RETRY_DELAYS, time_left)

    def download(self, url: str, target: Path) -> None:
        """Stream to a .part file and rename it when complete."""
        part = target.with_name(target.name + ".part")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._with_retries(lambda: self._download_once(url, part), _DOWNLOAD_RETRY_DELAYS)
            part.replace(target)
        except OSError as error:
            raise OutputFileError(f"Cannot write {target}: {error.strerror}.") from error

    def _with_retries[T](
        self,
        call: Callable[[], T],
        delays: tuple[float, ...],
        time_left: Callable[[], float] = lambda: math.inf,
    ) -> T:
        for delay in delays:
            try:
                return call()
            except SeedanceError as error:
                left = time_left()
                if not error.retryable or left <= 0:
                    raise
                wanted = delay if error.retry_after is None else error.retry_after
                self._sleep(min(wanted, left))

        # Last try: its error goes to the caller.
        return call()

    def _get_once(self, path: str) -> dict[str, Any]:
        try:
            response = self._api.get(path)
        except httpx.HTTPError as error:
            raise NetworkError(f"The connection failed ({type(error).__name__}).") from error

        parsed = self._parse(response)
        if not response.is_success:
            _raise_api_error(response, parsed)
        if not isinstance(parsed, dict):
            raise ServerError(
                "The API sent an answer that is not valid JSON.",
                status=response.status_code,
                request_id=response.headers.get(_REQUEST_ID_HEADER),
            )
        return parsed

    def _download_once(self, url: str, part: Path) -> None:
        # Error texts never hold the URL: it is a signed link.
        try:
            with self._storage.stream("GET", url) as response:
                _check_storage_status(response.status_code)
                with part.open("wb") as file:
                    for chunk in response.iter_bytes():
                        file.write(chunk)
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise NetworkError(f"The download failed ({type(error).__name__}).") from error

    def _parse(self, response: httpx.Response) -> Any:
        # Hide the key first, in case an answer ever repeats it.
        text = response.text.replace(self._api_key, _HIDDEN_KEY)
        try:
            return json.loads(text)
        except ValueError:
            return None


def _raise_unknown(response: httpx.Response, parsed: Any, reason: str) -> NoReturn:
    error = CreateOutcomeUnknown(
        f"The request was sent but its result is not known ({reason}). "
        "The task may or may not exist."
    )
    error.status = response.status_code
    error.code = _error_text(parsed, "code")
    error.request_id = _request_id(response, parsed)
    raise error


def _raise_api_error(response: httpx.Response, parsed: Any) -> NoReturn:
    status = response.status_code
    code = _error_text(parsed, "code")
    message = _error_text(parsed, "message") or f"The API answered HTTP {status}."

    # On a read, a 404 with no better meaning is a missing task.
    error_class = classify_error(status, code)
    is_read = response.request.method == "GET"
    if is_read and status == HTTP_NOT_FOUND and error_class is ApiError:
        error_class = TaskNotFoundError

    error = error_class(message, status, code, _request_id(response, parsed))
    error.retry_after = _parse_delay(response.headers.get("Retry-After"))
    raise error


def _error_text(parsed: Any, field: str) -> str | None:
    """One text field of the error object, or None if it is missing or not text."""
    error = parsed.get("error") if isinstance(parsed, dict) else None
    value = error.get(field) if isinstance(error, dict) else None
    return value if isinstance(value, str) else None


def _request_id(response: httpx.Response, parsed: Any) -> str | None:
    # The header is the first source. The message text also holds the ID.
    header = response.headers.get(_REQUEST_ID_HEADER)
    if header:
        return header
    found = _REQUEST_ID_TEXT.search(_error_text(parsed, "message") or "")
    return found[1] if found else None


def _parse_delay(value: str | None) -> float | None:
    # Only a plain number is used. A date or a broken value is ignored.
    try:
        seconds = float(value or "")
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, _RETRY_AFTER_CAP)


def _check_storage_status(status: int) -> None:
    # Our assumption: the docs do not say what an expired link returns.
    if status in (HTTP_FORBIDDEN, HTTP_NOT_FOUND):
        raise OutputUrlExpiredError(
            f"The storage host refused the link (HTTP {status}). We assume that it has expired "
            "(links last 24 hours) or that its download limit is reached."
        )
    if status >= HTTP_SERVER_ERROR:
        raise ServerError(f"The storage host answered HTTP {status}.", status=status)
    if not httpx.codes.is_success(status):
        raise ApiError(f"The storage host answered HTTP {status}.", status=status)
