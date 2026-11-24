"""Driver layer: the append-only state file that makes create safe to resume."""

import json
import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from seedance_client.errors import JournalError

_HOME_VARIABLE = "SEEDANCE_HOME"
_DEFAULT_FOLDER = ".seedance"
_FILE_NAME = "journal.jsonl"
_ATTEMPT_ID_BYTES = 8


class Event(StrEnum):
    """What happened. An attempt is one run of create."""

    SUBMITTING = "submitting"
    CREATED = "created"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    RESOLVED = "resolved"
    FINISHED = "finished"


_CLOSING_EVENTS = {Event.CREATED, Event.REJECTED, Event.RESOLVED}


def new_attempt_id() -> str:
    """A random ID that ties the events of one create run together."""
    return secrets.token_hex(_ATTEMPT_ID_BYTES)


def _find_path() -> Path:
    # One fixed place per user. A place that depends on the current folder would
    # hide an open attempt from a create that runs in another folder.
    override = os.environ.get(_HOME_VARIABLE)
    if not override:
        return Path.home() / _DEFAULT_FOLDER / _FILE_NAME

    folder = Path(override).expanduser()
    if not folder.is_absolute():
        raise JournalError(f"{_HOME_VARIABLE} must be a full path, not '{override}'.")
    return folder / _FILE_NAME


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Journal:
    """One JSON object per line. Lines are only ever added."""

    def __init__(self, clock: Callable[[], datetime] = _utc_now):
        self._clock = clock

    def append(self, event: Event, **fields: Any) -> None:
        """Write one line and force it to disk before returning."""
        path = _find_path()
        line = json.dumps({"ts": self._clock().isoformat(), "event": event, **fields})

        # fsync: a crash right after this call must not lose the line.
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")
                file.flush()
                os.fsync(file.fileno())
        except OSError as error:
            raise JournalError(f"Cannot write {path}: {error.strerror}.") from error

    def open_attempts(self) -> list[dict[str, Any]]:
        """Submitting events with no closing event: their outcome is not known."""
        entries = self._read()
        closed = {e.get("attempt") for e in entries if e["event"] in _CLOSING_EVENTS}
        return [
            e for e in entries if e["event"] == Event.SUBMITTING and e.get("attempt") not in closed
        ]

    def newest_task_id(self) -> str | None:
        """The task ID of the last created event."""
        for entry in reversed(self._read()):
            if entry["event"] == Event.CREATED:
                return entry.get("task_id")
        return None

    def _read(self) -> list[dict[str, Any]]:
        path = _find_path()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        except (OSError, UnicodeDecodeError) as error:
            raise JournalError(f"Cannot read {path}.") from error

        # A damaged line may hide an open attempt, so stop instead of skipping it.
        entries = []
        for number, line in enumerate(lines, start=1):
            entry = _parse_line(line)
            if entry is None:
                raise JournalError(
                    f"Line {number} of {path} is damaged. Check the task list at "
                    "BytePlus (see TROUBLESHOOTING.md), then remove that line."
                )
            entries.append(entry)
        return entries


def _parse_line(line: str) -> dict[str, Any] | None:
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if not isinstance(entry, dict) or "event" not in entry:
        return None
    return entry
