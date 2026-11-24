"""Keeps every test away from the network, the real key and the project folder."""

import json
import os
import socket
from pathlib import Path

import httpx
import pytest

from seedance_client.client import SeedanceClient


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEEDANCE_HOME", str(tmp_path / "state"))

    def refuse(*_args, **_kwargs):
        pytest.fail("A test tried to open a real connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


MARKER_KEY = "marker-key-0123456789"
TASKS_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
VIDEO_URL = "https://storage.example.com/video.mp4?signature=abc"
TASK_ID = "cgt-2026-test"


class FakeApi:
    """Answers requests from a list, in order, and records them.

    A reply is a response or an exception to raise.
    """

    def __init__(self):
        self.requests = []
        self.replies = []

    def __call__(self, request):
        self.requests.append(request)
        if not self.replies:
            pytest.fail(f"Unexpected request: {request.method} {request.url}")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def count(self, method):
        return sum(request.method == method for request in self.requests)


class FakeTime:
    """A clock that moves only when something sleeps."""

    def __init__(self):
        self.time = 0.0
        self.sleeps = []

    def now(self):
        return self.time

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.time += seconds


def error_reply(status, code, message="Some text.", headers=None):
    body = {"error": {"code": code, "message": message, "param": "", "type": "T"}}
    return httpx.Response(status, json=body, headers={"x-request-id": "req-1", **(headers or {})})


def task_reply(status, **fields):
    body = {
        "id": TASK_ID,
        "model": "seedance-1-0-pro-250528",
        "status": status,
        "resolution": "480p",
        "ratio": "16:9",
        "duration": 5,
        "service_tier": "default",
        **fields,
    }
    return httpx.Response(200, json=body)


def success_reply():
    return task_reply(
        "succeeded",
        content={"video_url": VIDEO_URL},
        usage={"completion_tokens": 48600, "total_tokens": 48600},
    )


def created_reply():
    return httpx.Response(200, json={"id": TASK_ID})


def journal_path():
    return Path(os.environ["SEEDANCE_HOME"]) / "journal.jsonl"


def read_journal():
    path = journal_path()
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def journal_events():
    return [entry["event"] for entry in read_journal()]


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def clock():
    return FakeTime()


@pytest.fixture
def make_client(api, clock, monkeypatch):
    """Builds clients that share one fake API and one fake clock."""
    monkeypatch.setenv("ARK_API_KEY", MARKER_KEY)

    def build():
        return SeedanceClient(clock.sleep, clock.now, http=httpx.MockTransport(api))

    return build


@pytest.fixture
def client(make_client):
    return make_client()
