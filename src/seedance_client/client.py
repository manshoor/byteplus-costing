"""Domain layer: create, get, wait and download a video task."""

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from seedance_client.catalog import Mode, ServiceTier, load_catalog, load_prices
from seedance_client.errors import (
    CreateInterrupted,
    CreateOutcomeUnknown,
    InvalidInputError,
    JournalError,
    MissingKeyError,
    NoTaskError,
    OpenAttemptError,
    OutputFileError,
    SeedanceError,
    TaskFailedError,
    TaskNotReadyError,
    WaitTimeoutError,
)
from seedance_client.journal import Event, Journal, new_attempt_id
from seedance_client.pricing import Estimate, cost_of, find_price, make_estimate
from seedance_client.transport import Transport
from seedance_client.validation import VideoRequest, find_problems, find_prompt_problems

_KEY_VARIABLE = "ARK_API_KEY"

# Our choices, not from the docs.
_FIRST_POLL_DELAY = 5.0
_POLL_GROWTH = 1.5
_MAX_POLL_DELAY = 30.0
DEFAULT_WAIT_TIMEOUT = 900.0

_TASKS_PATH = "/contents/generations/tasks"
_OUTPUT_DIR = Path("outputs")
_SUCCEEDED = "succeeded"
_FAILED_STATES = frozenset({"failed", "expired", "cancelled"})


class OverwritePolicy(Enum):
    """What download does when the file exists."""

    REFUSE = "refuse"
    REPLACE = "replace"


@dataclass(frozen=True)
class Task:
    """One video task as the API reports it. raw is the full answer."""

    task_id: str
    status: str
    model: str | None
    resolution: str | None
    service_tier: str | None
    video_url: str | None = field(repr=False)
    tokens: int | None
    error_code: str | None
    error_message: str | None
    raw: dict[str, Any] = field(repr=False)

    @property
    def is_final(self) -> bool:
        """True if the status cannot change. An unknown status is not final."""
        return self.status == _SUCCEEDED or self.status in _FAILED_STATES


class SeedanceClient:
    """Ties together the journal and the HTTP layer."""

    def __init__(
        self,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
        journal: Journal | None = None,
        http: httpx.BaseTransport | None = None,
    ) -> None:
        self._sleep = sleep
        self._now = now
        self._journal = journal or Journal()
        self._http = http
        self._transport: Transport | None = None

    def close(self) -> None:
        """Close the HTTP connections, if any were opened."""
        if self._transport is not None:
            self._transport.close()

    def check_key(self) -> None:
        """Raise MissingKeyError now, before the user is asked to confirm."""
        self._get_transport()

    # --- Create ---

    def check_request(self, request: VideoRequest) -> None:
        """Raise one error that lists every broken rule."""
        _raise_problems(find_problems(request, load_catalog()) + find_prompt_problems(request))

    def estimate(self, request: VideoRequest) -> Estimate:
        """Estimate the cost. Needs no key, no network and no prompt."""
        _raise_problems(find_problems(request, load_catalog()))
        return make_estimate(request, load_catalog(), load_prices())

    def check_open_attempts(self) -> None:
        """Raise if an earlier create has no known outcome."""
        attempts = self._journal.open_attempts()
        if not attempts:
            return
        listed = "\n".join(f"  - {_describe_attempt(attempt)}" for attempt in attempts)
        raise OpenAttemptError(
            f"An earlier create has no known outcome, so a paid task may exist:\n{listed}",
            [attempt.get("tier") for attempt in attempts],
        )

    def resolve_attempts(self) -> None:
        """Record that the user checked the task list for every open attempt."""
        for attempt in self._journal.open_attempts():
            self._journal.append(Event.RESOLVED, attempt=attempt["attempt"])

    def create(self, request: VideoRequest) -> str:
        """Send one paid request, exactly once, and return the task ID."""
        self.check_request(request)
        self.check_open_attempts()
        transport = self._get_transport()
        estimate = self.estimate(request)

        # Written before the POST: if this process dies, the attempt stays open.
        attempt = new_attempt_id()
        self._journal.append(
            Event.SUBMITTING,
            attempt=attempt,
            model=request.model,
            resolution=request.resolution,
            ratio=request.ratio,
            duration=request.duration,
            tier=request.service_tier,
            mode=request.mode,
            prompt=request.prompt,
        )

        # An unknown outcome does not close the attempt. A clear refusal does.
        try:
            answer = transport.post_once(_TASKS_PATH, _build_body(request))
        except CreateOutcomeUnknown as error:
            error.set_tiers([request.service_tier.value])
            self._record_failure(Event.UNKNOWN, attempt, error, reason=str(error))
            raise
        except SeedanceError as error:
            code = error.code or type(error).__name__
            self._record_failure(Event.REJECTED, attempt, error, code=code)
            raise

        # Ctrl-C here must not lose the ID. The attempt stays open.
        task_id = answer["id"]
        try:
            self._record_created(attempt, task_id, estimate)
        except KeyboardInterrupt as interrupt:
            raise CreateInterrupted(task_id) from interrupt
        return task_id

    def _record_failure(
        self, event: Event, attempt: str, error: SeedanceError, **fields: str
    ) -> None:
        try:
            self._journal.append(
                event,
                attempt=attempt,
                **fields,
                http_status=error.status,
                request_id=error.request_id,
            )
        except JournalError as journal_error:
            # What happened to the request matters more than the journal.
            error.args = (f"{error} The journal also failed: {journal_error}",)

    def _record_created(self, attempt: str, task_id: str, estimate: Estimate) -> None:
        # The ID is the only handle on a paid task, so show it if it cannot be saved.
        try:
            self._journal.append(
                Event.CREATED,
                attempt=attempt,
                task_id=task_id,
                estimate_usd=_estimate_record(estimate),
            )
        except JournalError as error:
            raise JournalError(
                f"Task {task_id} was created but not recorded. Write this ID down. {error}"
            ) from error

    # --- Read ---

    def resolve_task_id(self, task_id: str | None) -> str:
        """Use the given ID, or the newest created one in the journal."""
        found = task_id or self._journal.newest_task_id()
        if not found:
            raise NoTaskError("No task ID was given and the journal holds none.")
        return found

    def get_task(self, task_id: str, time_left: Callable[[], float] = lambda: math.inf) -> Task:
        """Read one task. Retries stop when no time is left."""
        path = f"{_TASKS_PATH}/{quote(task_id, safe='')}"
        raw = self._get_transport().get_json(path, time_left)
        return _parse_task(task_id, raw)

    def wait(
        self,
        task_id: str,
        timeout: float = DEFAULT_WAIT_TIMEOUT,
        on_poll: Callable[[Task], None] = lambda _task: None,
    ) -> Task:
        """Poll until the task is final. Raise if it did not succeed."""
        deadline = self._now() + timeout
        delay = _FIRST_POLL_DELAY

        while True:
            task = self._poll_once(task_id, deadline, timeout)
            on_poll(task)
            if task.is_final:
                break

            # Never sleep past the deadline.
            remaining = deadline - self._now()
            if remaining <= 0:
                raise WaitTimeoutError(
                    f"Task {task_id} is still '{task.status}' after {timeout:g} seconds. "
                    "It keeps running at BytePlus."
                )
            self._sleep(min(delay, remaining))
            delay = min(delay * _POLL_GROWTH, _MAX_POLL_DELAY)

        cost = self.list_cost(task)
        self._journal.append(
            Event.FINISHED,
            task_id=task_id,
            status=task.status,
            tokens=task.tokens,
            cost_usd=None if cost is None else str(cost),
        )
        _raise_if_failed(task)
        return task

    def _poll_once(self, task_id: str, deadline: float, timeout: float) -> Task:
        try:
            return self.get_task(task_id, lambda: deadline - self._now())
        except SeedanceError as error:
            if not error.retryable or self._now() < deadline:
                raise

            # The time ran out during retries. Keep the details of the last fault.
            stopped = WaitTimeoutError(
                f"Task {task_id} could not be read before the limit of {timeout:g} seconds "
                f"({error}). Its state is not known."
            )
            stopped.code, stopped.status = error.code, error.status
            stopped.request_id = error.request_id
            raise stopped from error

    def list_cost(self, task: Task) -> Decimal | None:
        """Cost from the list price and the API's token count, or None if unknown."""
        if task.status != _SUCCEEDED or task.tokens is None:
            return None
        try:
            tier = ServiceTier(task.service_tier)
        except ValueError:
            return None
        price = find_price(task.model or "", task.resolution or "", tier, load_prices())
        return cost_of(task.tokens, price)

    # --- Download ---

    def download(self, task_id: str, output: Path | None, policy: OverwritePolicy) -> Path:
        """Save the video of a succeeded task and return its path."""
        target = output or _OUTPUT_DIR / f"{Path(task_id).name}.mp4"
        if target.is_dir():
            raise OutputFileError(f"{target} is a folder.")
        if target.exists() and policy is OverwritePolicy.REFUSE:
            raise OutputFileError(f"{target} already exists.")

        task = self.get_task(task_id)
        _raise_if_failed(task)
        if task.status != _SUCCEEDED:
            raise TaskNotReadyError(f"Task {task_id} is '{task.status}', not finished yet.")
        if not task.video_url:
            raise TaskNotReadyError(f"Task {task_id} succeeded but has no video link.")

        self._get_transport().download(task.video_url, target)
        return target

    def _get_transport(self) -> Transport:
        # Made on first use, so estimate works with no key.
        if self._transport is None:
            self._transport = Transport(_load_key(), self._sleep, self._http)
        return self._transport


def _load_key() -> str:
    # The only place that reads the key.
    key = os.environ.get(_KEY_VARIABLE, "").strip()
    if not key:
        raise MissingKeyError(f"The environment variable {_KEY_VARIABLE} is not set or is empty.")

    # A bad character would make the HTTP library print the key in its own error.
    if not (key.isascii() and key.isprintable()):
        raise MissingKeyError(f"{_KEY_VARIABLE} holds characters that a key cannot have.")
    return key


def _raise_problems(problems: list[str]) -> None:
    if problems:
        raise InvalidInputError("\n".join(["The request is not valid:", *problems]))


def _build_body(request: VideoRequest) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if request.has_prompt:
        content.append({"type": "text", "text": request.prompt})
    if request.mode is Mode.IMAGE:
        image = {"type": "image_url", "image_url": {"url": request.image_url}}
        content.append({**image, "role": "first_frame"})

    body: dict[str, Any] = {
        "model": request.model,
        "content": content,
        "resolution": request.resolution,
        "ratio": request.ratio,
        "duration": request.duration,
    }

    # The default tier is left out, so the field is sent only when it changes something.
    if request.service_tier is ServiceTier.FLEX:
        body["service_tier"] = request.service_tier.value
    return body


def _estimate_record(estimate: Estimate) -> dict[str, str] | None:
    if estimate.low.cost is None or estimate.high.cost is None:
        return None
    return {"low": str(estimate.low.cost), "high": str(estimate.high.cost)}


def _describe_attempt(attempt: dict[str, Any]) -> str:
    return (
        f"{attempt.get('ts')} {attempt.get('model')} {attempt.get('resolution')} "
        f"{attempt.get('ratio')} {attempt.get('duration')} s, prompt: {attempt.get('prompt')}"
    )


def _parse_task(task_id: str, raw: dict[str, Any]) -> Task:
    content = _as_object(raw.get("content"))
    usage = _as_object(raw.get("usage"))
    error = _as_object(raw.get("error"))
    tokens = usage.get("completion_tokens")
    return Task(
        task_id=task_id,
        status=str(raw.get("status")),
        model=raw.get("model"),
        resolution=raw.get("resolution"),
        service_tier=raw.get("service_tier"),
        video_url=content.get("video_url"),
        tokens=tokens if isinstance(tokens, int) else None,
        error_code=error.get("code"),
        error_message=error.get("message"),
        raw=raw,
    )


def _as_object(value: Any) -> dict[str, Any]:
    # The API may leave a part out or send null.
    return value if isinstance(value, dict) else {}


def _raise_if_failed(task: Task) -> None:
    if task.status in _FAILED_STATES:
        raise TaskFailedError(task.task_id, task.status, task.error_code, task.error_message)
