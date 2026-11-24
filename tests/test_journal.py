from pathlib import Path

import pytest
from conftest import journal_path, read_journal

from seedance_client.errors import JournalError
from seedance_client.journal import Event, Journal


@pytest.fixture
def journal():
    return Journal()


def test_lines_are_only_added(journal):
    journal.append(Event.SUBMITTING, attempt="a")
    first = read_journal()
    journal.append(Event.CREATED, attempt="a", task_id="t1")
    assert read_journal()[:1] == first
    assert len(read_journal()) == 2
    assert first[0]["ts"].endswith("+00:00")


def test_every_line_reaches_disk(journal, monkeypatch):
    synced = []
    monkeypatch.setattr("os.fsync", synced.append)
    journal.append(Event.SUBMITTING, attempt="a")
    journal.append(Event.CREATED, attempt="a", task_id="t1")
    assert len(synced) == 2


@pytest.mark.parametrize("event", [Event.CREATED, Event.REJECTED, Event.RESOLVED])
def test_closing_events_close(journal, event):
    journal.append(Event.SUBMITTING, attempt="a")
    journal.append(event, attempt="a")
    assert journal.open_attempts() == []


@pytest.mark.parametrize("event", [None, Event.UNKNOWN, Event.FINISHED])
def test_other_events_stay_open(journal, event):
    journal.append(Event.SUBMITTING, attempt="a")
    if event is not None:
        journal.append(event, attempt="a")
    assert [entry["attempt"] for entry in journal.open_attempts()] == ["a"]


def test_attempts_are_independent(journal):
    journal.append(Event.SUBMITTING, attempt="a")
    journal.append(Event.SUBMITTING, attempt="b")
    journal.append(Event.CREATED, attempt="b", task_id="t1")
    assert [entry["attempt"] for entry in journal.open_attempts()] == ["a"]


def test_newest_task_id(journal):
    assert journal.newest_task_id() is None
    journal.append(Event.CREATED, attempt="a", task_id="t1")
    journal.append(Event.CREATED, attempt="b", task_id="t2")
    journal.append(Event.FINISHED, task_id="t1")
    assert journal.newest_task_id() == "t2"


@pytest.mark.parametrize("line", ['{"event": "submi', "[]", "{}"])
def test_damaged_line_stops(journal, line):
    journal_path().parent.mkdir()
    journal_path().write_text(line + "\n")
    with pytest.raises(JournalError, match="Line 1"):
        journal.open_attempts()


def test_unwritable_folder(journal):
    journal_path().parent.write_text("a file, not a folder")
    with pytest.raises(JournalError):
        journal.append(Event.SUBMITTING, attempt="a")


def test_default_place_is_home(journal, monkeypatch, tmp_path):
    monkeypatch.delenv("SEEDANCE_HOME")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    journal.append(Event.SUBMITTING, attempt="a")
    assert (tmp_path / "home/.seedance/journal.jsonl").exists()


def test_relative_home_is_refused(journal, monkeypatch):
    # A relative folder would change with the current folder.
    monkeypatch.setenv("SEEDANCE_HOME", "state")
    with pytest.raises(JournalError, match="full path"):
        journal.append(Event.SUBMITTING, attempt="a")
