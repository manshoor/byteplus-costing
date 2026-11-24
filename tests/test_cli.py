import io
import json
import traceback
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from conftest import (
    MARKER_KEY,
    TASK_ID,
    VIDEO_URL,
    created_reply,
    error_reply,
    journal_events,
    journal_path,
    success_reply,
    task_reply,
)

from seedance_client import catalog, cli
from seedance_client.errors import ExitCode, SeedanceError
from seedance_client.journal import Journal

COST = ["--model", "seedance-1-0-pro-250528", "--resolution", "480p"]
COST += ["--ratio", "16:9", "--duration", "5"]
CREATE = ["create", *COST, "--prompt", "A cat"]
COMMANDS = ["estimate", "create", "status", "wait", "download"]


@pytest.fixture
def run(make_client):
    """Runs one command line against the fake API."""
    return lambda *argv: cli.main(list(argv), make_client)


@pytest.fixture
def answer(monkeypatch):
    """Gives the program a terminal that types the given answers."""

    def set_answers(*answers):
        left = list(answers)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
        monkeypatch.setattr("builtins.input", lambda _question: left.pop(0))

    return set_answers


@pytest.fixture(autouse=True)
def no_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)


@pytest.fixture
def no_prices(monkeypatch):
    empty = replace(catalog.load_prices(), prices={})
    monkeypatch.setattr("seedance_client.client.load_prices", lambda: empty)


# --- Help and estimate: no key, no network ---


@pytest.mark.parametrize("argv", [["--help"], *([name, "--help"] for name in COMMANDS)])
def test_help_exits_zero(argv, capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == 0
    assert "usage: seedance" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["--model", "--resolution", "--ratio", "--duration"])
def test_cost_drivers_required(missing):
    at = COST.index(missing)
    with pytest.raises(SystemExit) as caught:
        cli.main(["estimate", *COST[:at], *COST[at + 2 :]])
    assert caught.value.code == 2


def test_estimate_needs_no_key(capsys):
    assert cli.main(["estimate", *COST]) == 0
    out = capsys.readouterr().out
    assert "5 s × 864 × 480 × 24 fps ÷ 1024 = 48,600 tokens" in out
    assert "48,600 × $2.5 ÷ 1,000,000 = $0.1215" in out
    assert "2026-11-23" in out
    assert "https://docs.byteplus.com/en/docs/modelark/model-pricing" in out
    assert "The bill uses the token count that the API returns" in out


def test_estimate_flex(capsys):
    assert cli.main(["estimate", *COST, "--service-tier", "flex"]) == 0
    assert "48,600 × $1.25 ÷ 1,000,000" in capsys.readouterr().out


def test_estimate_adaptive_range(capsys):
    image = ["--image-url", "https://example.com/cat.png"]
    argv = [*COST[:4], "--ratio", "adaptive", "--duration", "5", *image]
    assert cli.main(["estimate", *argv]) == 0
    out = capsys.readouterr().out
    assert "an indication" in out
    assert "not a bound" in out
    assert out.count("= $0.1") == 2


def test_estimate_all_problems(capsys):
    argv = ["--model", "seedance-1-0-pro-250528", "--resolution", "8k"]
    argv += ["--ratio", "2:1", "--duration", "5.5"]
    assert cli.main(["estimate", *argv]) == ExitCode.INVALID_INPUT
    err = capsys.readouterr().err
    assert all(word in err for word in ("Resolution", "Ratio", "whole number"))


def test_estimate_price_unknown(no_prices, capsys):
    assert cli.main(["estimate", *COST]) == 0
    assert "price unknown" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [[*CREATE, "--yes"], ["status", "x"], ["wait", "x"]])
def test_missing_key(argv, capsys):
    assert cli.main(argv) == ExitCode.MISSING_KEY
    err = capsys.readouterr().err
    assert "ARK_API_KEY" in err
    assert "uv run --env-file .env seedance" in err
    assert "export ARK_API_KEY" in err


# --- Create ---


def test_create_with_yes(run, api, capsys):
    api.replies = [created_reply()]
    assert run(*CREATE, "--yes") == 0
    out = capsys.readouterr().out
    assert out.index("$0.1215") < out.index(TASK_ID)


def test_create_asks_first(run, api, answer):
    answer("y")
    api.replies = [created_reply()]
    assert run(*CREATE) == 0
    assert api.count("POST") == 1


@pytest.mark.parametrize("text", ["", "n", "sure"])
def test_create_needs_a_yes(run, api, answer, text):
    answer(text)
    assert run(*CREATE) == ExitCode.NOT_CONFIRMED
    assert api.requests == []
    assert journal_events() == []


def test_create_without_terminal(run, api, capsys):
    assert run(*CREATE) == ExitCode.NOT_CONFIRMED
    assert api.requests == []
    assert "Nothing was sent" in capsys.readouterr().err


def test_unknown_price_no_yes(run, api, no_prices):
    assert run(*CREATE, "--yes") == ExitCode.NOT_CONFIRMED
    assert api.requests == []


def test_unknown_price_by_hand(run, api, no_prices, answer, capsys):
    answer("y")
    api.replies = [created_reply()]
    assert run(*CREATE) == 0
    assert "price unknown" in capsys.readouterr().out


@pytest.mark.parametrize("change", [["--duration", "99"], ["--prompt", " "]])
def test_bad_create_sends_nothing(run, api, change):
    assert run(*CREATE, *change, "--yes") == ExitCode.INVALID_INPUT
    assert api.requests == []


def test_long_prompt_warns(run, api, capsys):
    api.replies = [created_reply()]
    assert run(*CREATE, "--prompt", "word " * 1001, "--yes") == 0
    assert "Warning" in capsys.readouterr().out


def test_api_error_output(run, api, capsys):
    api.replies = [error_reply(404, "ModelNotOpen", "Model is not open.")]
    assert run(*CREATE, "--yes") == ExitCode.MODEL_ACCESS
    err = capsys.readouterr().err
    assert "Error: Model is not open." in err
    assert "Next: Activate the model" in err
    assert "Code: ModelNotOpen" in err
    assert "Request ID: req-1" in err


# --- Open attempts ---


@pytest.fixture
def open_attempt(run, api):
    """Leaves one create with an unknown outcome."""
    api.replies = [httpx.ReadTimeout("slow")]
    assert run(*CREATE, "--yes") == ExitCode.CREATE_UNKNOWN


def test_open_attempt_blocks_yes(open_attempt, run, api, capsys):
    assert run(*CREATE, "--yes") == ExitCode.OPEN_ATTEMPT
    assert api.count("POST") == 1
    assert "A cat" in capsys.readouterr().err


def test_attempt_blocks_elsewhere(open_attempt, run, api, monkeypatch, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert run(*CREATE, "--yes") == ExitCode.OPEN_ATTEMPT
    assert api.count("POST") == 1


def test_bad_prompt_is_rejected(run, api):
    assert run(*CREATE[:-1], "cat \udcff", "--yes") == ExitCode.INVALID_INPUT
    assert api.requests == []
    assert journal_events() == []


def test_odd_attempt_clears(run, api, monkeypatch):
    # An older journal may hold such a prompt, and a terminal may be ASCII only.
    out = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr("sys.stdout", out)
    Journal().append("submitting", attempt="a", prompt="chat \udcff é")
    api.replies = [created_reply()]
    assert run(*CREATE, "--yes", "--resolved") == 0
    assert "resolved" in journal_events()


def test_resolved_clears_attempt(open_attempt, run, api):
    api.replies = [created_reply()]
    assert run(*CREATE, "--yes", "--resolved") == 0
    assert api.count("POST") == 2
    assert "resolved" in journal_events()


def test_resolved_is_not_yes(open_attempt, run, api):
    assert run(*CREATE, "--resolved") == ExitCode.NOT_CONFIRMED
    assert api.count("POST") == 1


def test_attempt_answer_yes(open_attempt, run, api, answer):
    answer("y", "y")
    api.replies = [created_reply()]
    assert run(*CREATE) == 0
    assert "resolved" in journal_events()


def test_attempt_kept_on_no(open_attempt, run, api, answer):
    answer("n")
    assert run(*CREATE, "--yes") == ExitCode.OPEN_ATTEMPT
    assert api.count("POST") == 1
    assert "resolved" not in journal_events()


# --- Status, wait, download ---


def test_full_path_without_ids(run, api, capsys):
    api.replies = [created_reply(), task_reply("queued"), success_reply()]
    api.replies += [success_reply(), httpx.Response(200, content=b"video")]
    assert run(*CREATE, "--yes") == 0
    assert run("wait") == 0
    assert run("download") == 0
    assert Path("outputs", f"{TASK_ID}.mp4").read_bytes() == b"video"
    out = capsys.readouterr().out
    assert "Tokens: 48,600" in out
    assert "$0.1215 (computed from list price)" in out


def test_status_text(run, api, capsys):
    api.replies = [success_reply()]
    assert run("status", TASK_ID) == 0
    out = capsys.readouterr().out
    assert "Status: succeeded" in out
    assert "computed from list price" in out


def test_status_json(run, api, capsys):
    api.replies = [success_reply()]
    assert run("status", TASK_ID, "--json") == 0
    assert json.loads(capsys.readouterr().out)["content"]["video_url"] == VIDEO_URL


def test_status_of_failed_task(run, api, capsys):
    api.replies = [task_reply("failed", error={"code": "Some.Code", "message": "Why."})]
    assert run("status", TASK_ID) == 0
    assert "Some.Code: Why." in capsys.readouterr().out


def test_no_task_yet(run):
    assert run("status") == ExitCode.NO_TASK


def test_wait_failed_task(run, api, capsys):
    api.replies = [task_reply("failed", error={"code": "Some.Code", "message": "Why."})]
    assert run("wait", TASK_ID) == ExitCode.TASK_FAILED
    assert "Code: Some.Code" in capsys.readouterr().err


def test_wait_timeout_option(run, api, capsys):
    api.replies = [task_reply("running")] * 2
    assert run("wait", TASK_ID, "--timeout", "3") == ExitCode.WAIT_TIMEOUT
    assert "seedance wait" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "soon"])
def test_bad_timeout(run, value):
    with pytest.raises(SystemExit) as caught:
        run("wait", TASK_ID, "--timeout", value)
    assert caught.value.code == 2


def test_interrupt_is_clean(run, api, capsys):
    api.replies = [KeyboardInterrupt()]
    assert run("wait", TASK_ID) == ExitCode.INTERRUPTED
    assert "keeps running" in capsys.readouterr().err


def test_download_expired_link(run, api, capsys):
    api.replies = [success_reply(), httpx.Response(403)]
    assert run("download", TASK_ID) == ExitCode.OUTPUT_URL_EXPIRED
    assert "24 hours" in capsys.readouterr().err


# --- The key and the video link never leak ---

ECHO = error_reply(401, "AuthenticationError", f"Bad key {MARKER_KEY}.")


@pytest.mark.parametrize(
    "replies",
    [
        [created_reply(), success_reply(), success_reply(), httpx.Response(200, content=b"v")],
        [ECHO, ECHO, ECHO],
        [httpx.ReadTimeout("x"), httpx.ConnectError("x"), error_reply(404, "NotFound.Task")],
        [httpx.Response(500, text=MARKER_KEY), ECHO, ECHO],
        [created_reply(), task_reply("failed"), success_reply(), httpx.Response(403)],
    ],
)
def test_key_never_leaks(run, api, capsys, caplog, replies):
    caplog.set_level("DEBUG")

    # A network fault on a read is retried, so repeat the last reply as needed.
    api.replies = replies + [replies[-1]] * 20
    run(*CREATE, "--yes")
    run("wait", TASK_ID)
    run("download", TASK_ID)
    run("status", TASK_ID, "--json")

    shown = capsys.readouterr()
    journal = journal_path().read_text()
    for text in (shown.out, shown.err, caplog.text, journal):
        assert MARKER_KEY not in text
    assert "signature" not in journal


@pytest.mark.parametrize("reply", [ECHO, httpx.ReadTimeout("x"), httpx.Response(500)])
def test_key_not_in_traceback(client, api, reply):
    # A traceback shows the error and every error it came from.
    api.replies = [reply] * 5
    with pytest.raises(SeedanceError) as caught:
        client.get_task(TASK_ID)
    assert MARKER_KEY not in "".join(traceback.format_exception(caught.value))
