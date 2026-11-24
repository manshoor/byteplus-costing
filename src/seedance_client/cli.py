"""UI layer: command line, prompts, output and exit codes."""

import argparse
import io
import json
import math
import sys
from collections.abc import Callable, Sequence
from decimal import Decimal
from enum import Enum
from pathlib import Path

from seedance_client.catalog import ADAPTIVE_RATIO, ServiceTier, load_catalog, load_prices
from seedance_client.client import (
    DEFAULT_WAIT_TIMEOUT,
    OverwritePolicy,
    SeedanceClient,
    Task,
)
from seedance_client.errors import (
    CreateInterrupted,
    ExitCode,
    NotConfirmedError,
    OpenAttemptError,
    SeedanceError,
)
from seedance_client.pricing import PIXELS_PER_TOKEN, PRICE_UNIT_TOKENS, Estimate, SizeEstimate
from seedance_client.validation import VideoRequest, find_warnings

_YES_ANSWERS = {"y", "yes"}


class _CostAnswer(Enum):
    """How the cost is confirmed."""

    ASK = "ask"
    YES = "yes"


class _AttemptAnswer(Enum):
    """How an open attempt is cleared."""

    ASK = "ask"
    RESOLVED = "resolved"


class _Format(Enum):
    """How status is printed."""

    TEXT = "text"
    JSON = "json"


def main(
    argv: Sequence[str] | None = None,
    make_client: Callable[[], SeedanceClient] = SeedanceClient,
) -> int:
    """Run one command and return its exit code."""
    _allow_odd_characters()
    args = _build_parser().parse_args(argv)
    client = make_client()
    try:
        args.run(client, args)
    except SeedanceError as error:
        _print_error(error)
        return error.exit_code
    except CreateInterrupted as stopped:
        print(f"\nStopped. {stopped} Write this ID down.", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except KeyboardInterrupt:
        _print_stopped(args.command)
        return ExitCode.INTERRUPTED
    finally:
        client.close()
    return ExitCode.OK


def _allow_odd_characters() -> None:
    # Show a character the terminal cannot print as a code, instead of crashing.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="backslashreplace")


# --- Parser ---


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seedance",
        description="Create Seedance videos on BytePlus ModelArk. Independent sample, "
        "not affiliated with BytePlus.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    # estimate and create share the options that set the cost.
    estimate = commands.add_parser("estimate", help="show the estimated cost (no key needed)")
    _add_request_options(estimate)
    estimate.set_defaults(run=_run_estimate, prompt=None)

    create = commands.add_parser("create", help="send one paid request")
    _add_request_options(create)
    create.add_argument("--prompt", help="what the video shows; required without --image-url")
    create.add_argument(
        "--yes",
        dest="cost_answer",
        action="store_const",
        const=_CostAnswer.YES,
        default=_CostAnswer.ASK,
        help="accept the estimated cost without a question",
    )
    create.add_argument(
        "--resolved",
        dest="attempt_answer",
        action="store_const",
        const=_AttemptAnswer.RESOLVED,
        default=_AttemptAnswer.ASK,
        help="say that you checked the task list at BytePlus after an unclear create",
    )
    create.set_defaults(run=_run_create)

    status = commands.add_parser("status", help="show a task once")
    _add_task_id(status)
    status.add_argument(
        "--json",
        dest="format",
        action="store_const",
        const=_Format.JSON,
        default=_Format.TEXT,
        help="print the full API answer, including the video link",
    )
    status.set_defaults(run=_run_status)

    wait = commands.add_parser("wait", help="wait until a task ends")
    _add_task_id(wait)
    wait.add_argument(
        "--timeout",
        type=_parse_timeout,
        default=DEFAULT_WAIT_TIMEOUT,
        metavar="SECONDS",
        help=f"stop waiting after this time (default {DEFAULT_WAIT_TIMEOUT:g})",
    )
    wait.set_defaults(run=_run_wait)

    download = commands.add_parser("download", help="save the video of a finished task")
    _add_task_id(download)
    download.add_argument("--output", type=Path, help="file path (default outputs/TASK_ID.mp4)")
    download.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_const",
        const=OverwritePolicy.REPLACE,
        default=OverwritePolicy.REFUSE,
        help="replace the file if it exists",
    )
    download.set_defaults(run=_run_download)
    return parser


def _add_request_options(parser: argparse.ArgumentParser) -> None:
    # No defaults for the cost drivers: each one must be an explicit choice.
    models = ", ".join(load_catalog().models)
    parser.add_argument("--model", required=True, help=f"one of: {models}")
    parser.add_argument("--resolution", required=True, help="480p, 720p, 1080p or 4k")
    parser.add_argument("--ratio", required=True, help="for example 16:9, or adaptive")
    parser.add_argument(
        "--duration", required=True, type=_parse_duration, help="length in whole seconds"
    )
    parser.add_argument(
        "--service-tier",
        type=ServiceTier,
        choices=list(ServiceTier),
        default=ServiceTier.DEFAULT,
        help="flex is offline, at half price, on 1.0 models only",
    )
    parser.add_argument("--image-url", help="public URL of the first frame")


def _add_task_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "task_id", nargs="?", metavar="TASK_ID", help="default: the newest task in the journal"
    )


def _parse_duration(text: str) -> int | str:
    # Bad text goes on to validation, which reports all problems at once.
    try:
        return int(text)
    except ValueError:
        return text


def _parse_timeout(text: str) -> float:
    seconds = float(text)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError("must be zero or more seconds")
    return seconds


def _read_request(args: argparse.Namespace) -> VideoRequest:
    return VideoRequest(
        model=args.model,
        resolution=args.resolution,
        ratio=args.ratio,
        duration=args.duration,
        service_tier=args.service_tier,
        prompt=args.prompt,
        image_url=args.image_url,
    )


# --- Commands ---


def _run_estimate(client: SeedanceClient, args: argparse.Namespace) -> None:
    _print_estimate(client.estimate(_read_request(args)))


def _run_create(client: SeedanceClient, args: argparse.Namespace) -> None:
    request = _read_request(args)
    client.check_request(request)
    for warning in find_warnings(request):
        print(f"Warning: {warning}")

    # All free checks come before the question about money.
    client.check_key()
    _clear_open_attempts(client, args.attempt_answer)
    estimate = client.estimate(request)
    _print_estimate(estimate)
    _confirm_cost(estimate, args.cost_answer)

    task_id = client.create(request)
    print(f"\nTask created: {task_id}")
    print("Next: seedance wait")


def _run_status(client: SeedanceClient, args: argparse.Namespace) -> None:
    task = client.get_task(client.resolve_task_id(args.task_id))
    if args.format is _Format.JSON:
        print(json.dumps(task.raw, indent=2))
        return

    print(f"Task: {task.task_id}")
    print(f"Status: {task.status}")
    if task.error_code or task.error_message:
        print(f"Error: {task.error_code}: {task.error_message}")
    _print_usage(client, task)


def _run_wait(client: SeedanceClient, args: argparse.Namespace) -> None:
    task_id = client.resolve_task_id(args.task_id)
    print(f"Task: {task_id}")
    task = client.wait(
        task_id, args.timeout, lambda task: print(f"Status: {task.status}", flush=True)
    )
    _print_usage(client, task)
    print("Next: seedance download (the link is valid for 24 hours)")


def _run_download(client: SeedanceClient, args: argparse.Namespace) -> None:
    task_id = client.resolve_task_id(args.task_id)
    path = client.download(task_id, args.output, args.overwrite)
    print(f"Saved: {path}")


# --- Questions ---


def _clear_open_attempts(client: SeedanceClient, answer: _AttemptAnswer) -> None:
    try:
        client.check_open_attempts()
        return
    except OpenAttemptError as error:
        if answer is _AttemptAnswer.ASK and not sys.stdin.isatty():
            raise
        print(f"{error}\n{error.next_step}")
        if answer is _AttemptAnswer.ASK and not _ask("I checked the task list [y/N] "):
            raise
    client.resolve_attempts()


def _confirm_cost(estimate: Estimate, answer: _CostAnswer) -> None:
    price_known = estimate.price is not None
    if answer is _CostAnswer.YES and price_known:
        return
    if answer is _CostAnswer.YES:
        raise NotConfirmedError("The price is unknown, so --yes is refused. Nothing was sent.")
    if not sys.stdin.isatty():
        raise NotConfirmedError("There is no terminal to ask for a yes. Nothing was sent.")
    if not _ask("\nSend this paid request? [y/N] "):
        raise NotConfirmedError("You did not answer yes. Nothing was sent.")


def _ask(question: str) -> bool:
    try:
        return input(question).strip().lower() in _YES_ANSWERS
    except EOFError:
        return False


# --- Output ---


def _print_estimate(estimate: Estimate) -> None:
    request = estimate.request
    prices = load_prices()
    print("Estimated cost")
    print(f"Model: {request.model}, {request.resolution}, {request.mode} to video")

    # An adaptive ratio has no known size, so show both ends of the range.
    if request.ratio == ADAPTIVE_RATIO:
        print("The API picks the size for an adaptive ratio. The range is an indication from")
        print("the six standard shapes, not a bound. The real cost can be outside it.")
        _print_tokens("Low", estimate, estimate.low)
        _print_tokens("High", estimate, estimate.high)
    else:
        _print_tokens("Tokens", estimate, estimate.low)

    if estimate.price is None:
        print(
            f"Cost: price unknown. pricing.toml has no price for {request.model} "
            f"at {request.resolution}, tier {request.service_tier}."
        )
    else:
        print(f"Price: ${estimate.price} per {PRICE_UNIT_TOKENS:,} tokens", end="")
        print(f" (list price, tier {request.service_tier})")
        _print_cost(estimate, estimate.low)
        if estimate.low != estimate.high:
            _print_cost(estimate, estimate.high)

    print(f"Prices read on {prices.read_on} from {prices.source_url}")
    print("This is an estimate. The bill uses the token count that the API returns.")


def _print_tokens(label: str, estimate: Estimate, size: SizeEstimate) -> None:
    print(
        f"{label} ({size.ratio}): {estimate.request.duration} s × {size.width} × {size.height} "
        f"× {estimate.frame_rate} fps ÷ {PIXELS_PER_TOKEN} = {_format_tokens(size.tokens)} tokens"
    )


def _print_cost(estimate: Estimate, size: SizeEstimate) -> None:
    print(
        f"Cost: {_format_tokens(size.tokens)} × ${estimate.price} ÷ {PRICE_UNIT_TOKENS:,} "
        f"= {_format_cost(size.cost)}"
    )


def _print_usage(client: SeedanceClient, task: Task) -> None:
    if task.tokens is None:
        return
    print(f"Tokens: {task.tokens:,}")
    print(f"Cost: {_format_cost(client.list_cost(task))} (computed from list price)")
    print("This tool cannot show the billed amount. In the console, Billing overview shows the")
    print("account balance and Usage statistics shows token usage.")


def _format_tokens(tokens: Decimal) -> str:
    # normalize drops zeros after the point: 48600.0 becomes 48,600.
    return f"{tokens.normalize():,f}"


def _format_cost(cost: Decimal | None) -> str:
    return "price unknown" if cost is None else f"${cost:.4f}"


def _print_error(error: SeedanceError) -> None:
    lines = [f"Error: {error}", f"Next: {error.next_step}"]
    if error.code:
        lines.append(f"Code: {error.code}")
    if error.status:
        lines.append(f"HTTP status: {error.status}")
    if error.request_id:
        lines.append(f"Request ID: {error.request_id}")
    print("\n".join(lines), file=sys.stderr)


def _print_stopped(command: str) -> None:
    if command == "create":
        text = "If the request was already sent, the next create asks you to check the task list."
    else:
        text = "A created task keeps running at BytePlus. Run the same command to resume."
    print(f"\nStopped. {text}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
