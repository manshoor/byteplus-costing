"""Error classes, exit codes, and the mapping from API errors to classes."""

from collections.abc import Iterable
from enum import IntEnum

HTTP_BAD_REQUEST = 400
_HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
_HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR = 500


class ExitCode(IntEnum):
    """Process exit codes. 2 is used by argparse for a wrong command line."""

    OK = 0
    GENERAL = 1
    MISSING_KEY = 3
    AUTH = 4
    ACCOUNT = 5
    MODEL_ACCESS = 6
    INVALID_INPUT = 7
    CONTENT_REJECTED = 8
    RATE_LIMIT = 9
    QUOTA = 10
    SERVER = 11
    NETWORK = 12
    TASK_NOT_FOUND = 13
    TASK_FAILED = 14
    WAIT_TIMEOUT = 15
    OUTPUT_URL_EXPIRED = 16
    CREATE_UNKNOWN = 17
    OPEN_ATTEMPT = 18
    NOT_CONFIRMED = 19
    JOURNAL = 20
    NO_TASK = 21
    TASK_NOT_READY = 22
    OUTPUT_FILE = 23
    INTERRUPTED = 130


_TASKS_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
_ALL_TIERS = frozenset({"default", "flex"})


def _list_advice(tiers: Iterable[str | None]) -> str:
    """How to find a task without its ID, with one curl line per service tier.

    The List tasks API shows online tasks only, unless it is asked for flex.
    """
    # An attempt with no known tier may be in either list.
    wanted = set(tiers)
    if not wanted or not wanted <= _ALL_TIERS:
        wanted = set(_ALL_TIERS)

    lines = ["List your tasks first. Set ARK_API_KEY in this shell first (export)."]
    for tier in sorted(wanted):
        lines.append(
            '      curl -H "Authorization: Bearer $ARK_API_KEY" '
            f'"{_TASKS_URL}?page_num=1&filter.service_tier={tier}"'
        )
    lines.append("      Each tier has its own list. If you are not sure, check both tiers:")
    lines.append("      the value of service_tier is default or flex.")
    lines.append("      More pages may exist: raise page_num until a page is empty.")
    lines.append("      If your console shows a task list, you can check there too.")
    return "\n".join(lines)


class SeedanceError(Exception):
    """Base class. next_step tells the user what to do."""

    exit_code = ExitCode.GENERAL
    next_step = "Read the message above and try again."
    retryable = False
    code: str | None = None
    status: int | None = None
    request_id: str | None = None
    retry_after: float | None = None


# --- Local errors: raised by this project, not by the API ---


class MissingKeyError(SeedanceError):
    exit_code = ExitCode.MISSING_KEY
    next_step = (
        "Put ARK_API_KEY=your-key in a file named .env, then run: "
        "uv run --env-file .env seedance ...\n"
        "      Or set it in this terminal first: export ARK_API_KEY=your-key"
    )


class NetworkError(SeedanceError):
    exit_code = ExitCode.NETWORK
    next_step = "Check the internet connection and run the command again."
    retryable = True


class TaskFailedError(SeedanceError):
    exit_code = ExitCode.TASK_FAILED
    next_step = "Fix the cause, then create a new task. Only successful videos are charged."

    def __init__(
        self, task_id: str, task_status: str, code: str | None, message: str | None
    ) -> None:
        detail = f": {message}" if message else "."
        super().__init__(f"Task {task_id} ended as '{task_status}'{detail}")
        self.task_id = task_id
        self.task_status = task_status
        self.code = code


class WaitTimeoutError(SeedanceError):
    exit_code = ExitCode.WAIT_TIMEOUT
    next_step = "Run 'seedance wait' again to resume. Do not create a second task."


class OutputUrlExpiredError(SeedanceError):
    exit_code = ExitCode.OUTPUT_URL_EXPIRED
    next_step = (
        "Run 'seedance download' once more to ask for the task again. "
        "If that fails, send the task ID to support."
    )


class CreateOutcomeUnknown(SeedanceError):
    exit_code = ExitCode.CREATE_UNKNOWN

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.set_tiers([])

    def set_tiers(self, tiers: Iterable[str | None]) -> None:
        """Name the service tiers whose task list must be checked."""
        self.next_step = (
            f"{_list_advice(tiers)}\n      Do this before you run create again. "
            "A second request can make a second paid video."
        )


class OpenAttemptError(SeedanceError):
    exit_code = ExitCode.OPEN_ATTEMPT

    def __init__(self, message: str, tiers: Iterable[str | None]) -> None:
        super().__init__(message)
        self.next_step = (
            f"{_list_advice(tiers)}\n      Then run create again in a terminal "
            "and answer the question, or add --resolved."
        )


class CreateInterrupted(KeyboardInterrupt):
    """Ctrl-C after a task was created and before its ID was surely saved."""

    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task {task_id} was created but may not be recorded.")
        self.task_id = task_id


class NotConfirmedError(SeedanceError):
    exit_code = ExitCode.NOT_CONFIRMED
    next_step = "Run the command in a terminal and answer y, or add --yes if the price is known."


class JournalError(SeedanceError):
    exit_code = ExitCode.JOURNAL
    next_step = "Fix the journal file before you run create again."


class NoTaskError(SeedanceError):
    exit_code = ExitCode.NO_TASK
    next_step = "Give a task ID, or run 'seedance create' first."


class TaskNotReadyError(SeedanceError):
    exit_code = ExitCode.TASK_NOT_READY
    next_step = "Run 'seedance wait', then download again."


class OutputFileError(SeedanceError):
    exit_code = ExitCode.OUTPUT_FILE
    next_step = "Choose another path with --output, or add --overwrite to replace a file."


# --- API errors: carry the HTTP status, code and request ID ---


class ApiError(SeedanceError):
    next_step = "Send the code and the request ID to support."

    def __init__(
        self,
        message: str,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id


class AuthError(ApiError):
    exit_code = ExitCode.AUTH
    next_step = "Check that ARK_API_KEY holds a valid key for region ap-southeast-1."


class AccountError(ApiError):
    exit_code = ExitCode.ACCOUNT
    next_step = "Check the account status and balance in the BytePlus console."


class ModelAccessError(ApiError):
    exit_code = ExitCode.MODEL_ACCESS
    next_step = "Activate the model in the ModelArk console and check the key's model limits."


class InvalidInputError(ApiError):
    exit_code = ExitCode.INVALID_INPUT
    next_step = "Correct the request and run the command again."


class ContentRejectedError(InvalidInputError):
    exit_code = ExitCode.CONTENT_REJECTED
    next_step = "Change the prompt or the image and run the command again."


class RateLimitError(ApiError):
    exit_code = ExitCode.RATE_LIMIT
    next_step = "Wait a minute and run the command again."
    retryable = True


class QuotaError(ApiError):
    exit_code = ExitCode.QUOTA
    next_step = "Check the quota and the cumulative usage limit of this model."


class ServerError(ApiError):
    exit_code = ExitCode.SERVER
    next_step = "Try again later. If it continues, send the request ID to BytePlus support."
    retryable = True


class TaskNotFoundError(ApiError):
    exit_code = ExitCode.TASK_NOT_FOUND
    next_step = "Check the task ID. Task IDs are valid for 7 days, in one region and account."


_EXACT_CODES: dict[str, type[ApiError]] = {
    "AuthenticationError": AuthError,
    "InvalidAccountStatus": AccountError,
    "AccountOverdueError": AccountError,
    "OperationDenied.ServiceOverdue": AccountError,
    "ModelNotOpen": ModelAccessError,
    "OperationDenied.ServiceNotOpen": ModelAccessError,
    "AccessDenied": ModelAccessError,
    "QuotaExceeded": QuotaError,
    "SetLimitExceeded": QuotaError,
    "InflightBatchsizeExceeded": QuotaError,
    "ModelAccountRpmRateLimitExceeded": RateLimitError,
    "ModelAccountTpmRateLimitExceeded": RateLimitError,
    "APIAccountRpmRateLimitExceeded": RateLimitError,
    "AccountRateLimitExceeded": RateLimitError,
    "ServerOverloaded": RateLimitError,
    "RequestBurstTooFast": RateLimitError,
}

_CODE_PREFIXES: tuple[tuple[str, type[ApiError]], ...] = (
    ("InvalidEndpointOrModel.", ModelAccessError),
    ("InvalidParameter", InvalidInputError),
    ("MissingParameter", InvalidInputError),
    ("InvalidImageURL", InvalidInputError),
    ("RateLimitExceeded", RateLimitError),
)

_STATUS_FALLBACK: dict[int, type[ApiError]] = {
    HTTP_BAD_REQUEST: InvalidInputError,
    _HTTP_UNAUTHORIZED: AuthError,
    HTTP_FORBIDDEN: ModelAccessError,
    _HTTP_TOO_MANY_REQUESTS: RateLimitError,
}

_SENSITIVE_MARK = "SensitiveContentDetected"


def classify_error(status: int, code: str | None) -> type[ApiError]:
    """Pick a class by the code in the body first, then by the HTTP status."""
    code = code or ""
    if _SENSITIVE_MARK in code:
        return ContentRejectedError
    if code in _EXACT_CODES:
        return _EXACT_CODES[code]

    for prefix, error_class in _CODE_PREFIXES:
        if code.startswith(prefix):
            return error_class

    if status >= HTTP_SERVER_ERROR:
        return ServerError
    return _STATUS_FALLBACK.get(status, ApiError)
