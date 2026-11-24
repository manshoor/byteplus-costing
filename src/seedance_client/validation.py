"""Checks a request against models.toml before anything is sent."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from seedance_client.catalog import Catalog, Mode, Model, ServiceTier

_URL_PREFIXES = ("http://", "https://")
_AUTO_DURATION = -1
_PROMPT_WORD_ADVICE = 1000


@dataclass(frozen=True)
class VideoRequest:
    """What the user asked for. duration stays a string if it is not a whole number."""

    model: str
    resolution: str
    ratio: str
    duration: int | str
    service_tier: ServiceTier = ServiceTier.DEFAULT
    prompt: str | None = None
    image_url: str | None = None

    @property
    def mode(self) -> Mode:
        """Image to video if an image URL was given, else text to video."""
        return Mode.TEXT if self.image_url is None else Mode.IMAGE

    @property
    def has_prompt(self) -> bool:
        """True if the prompt holds more than blanks."""
        return bool(self.prompt and self.prompt.strip())


def find_problems(request: VideoRequest, catalog: Catalog) -> list[str]:
    """All broken rules that do not depend on the prompt."""
    problems = []
    if request.image_url is not None and not _is_web_url(request.image_url):
        problems.append("The image URL must start with http:// or https:// and name a host.")

    # The other rules depend on the model, so an unknown model ends the check.
    model = catalog.models.get(request.model)
    if model is None:
        known = ", ".join(catalog.models)
        problems.append(f"Unknown model '{request.model}'. Known models: {known}.")
        return problems

    if request.resolution not in model.resolutions:
        allowed = ", ".join(model.resolutions)
        problems.append(
            f"Resolution '{request.resolution}' is not allowed for {model.model_id}. "
            f"Allowed: {allowed}."
        )

    allowed_ratios = catalog.ratios[(model.series, request.mode)]
    if request.ratio not in allowed_ratios:
        problems.append(
            f"Ratio '{request.ratio}' is not allowed for series {model.series} "
            f"{request.mode} to video. Allowed: {', '.join(allowed_ratios)}."
        )

    problems += _duration_problems(request.duration, model)

    if request.service_tier is ServiceTier.FLEX and not model.offline_tier:
        problems.append(f"Service tier 'flex' is not supported by {model.model_id}.")

    return problems


def find_prompt_problems(request: VideoRequest) -> list[str]:
    """Text to video needs a prompt. Image to video does not."""
    if request.mode is Mode.TEXT and not request.has_prompt:
        return ["A prompt is required for text to video."]
    if not _is_utf8(request.prompt or ""):
        return ["The prompt holds characters that are not valid Unicode text."]
    return []


def find_warnings(request: VideoRequest) -> list[str]:
    """Things the docs advise against but do not forbid."""
    words = len((request.prompt or "").split())
    if words > _PROMPT_WORD_ADVICE:
        return [f"The prompt has {words} words. The docs advise at most {_PROMPT_WORD_ADVICE}."]
    return []


def _is_web_url(url: str) -> bool:
    if not url.startswith(_URL_PREFIXES) or not _is_utf8(url):
        return False

    # urlsplit rejects some broken hosts with ValueError.
    try:
        return bool(urlsplit(url).hostname)
    except ValueError:
        return False


def _is_utf8(text: str) -> bool:
    # A terminal can pass broken bytes, which JSON cannot carry.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _duration_problems(duration: int | str, model: Model) -> list[str]:
    if type(duration) is not int:
        return [f"Duration '{duration}' must be a whole number of seconds."]

    # The API accepts -1 (the model picks), but its cost cannot be estimated.
    if duration == _AUTO_DURATION:
        return ["Duration -1 (automatic) is not supported: its cost cannot be estimated."]

    if not model.min_duration <= duration <= model.max_duration:
        return [
            f"Duration {duration} is outside {model.min_duration} to {model.max_duration} "
            f"seconds for {model.model_id}."
        ]
    return []
