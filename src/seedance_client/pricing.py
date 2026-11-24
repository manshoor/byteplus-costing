"""Cost estimates and cost computed from a real token count."""

from dataclasses import dataclass
from decimal import Decimal

from seedance_client.catalog import ADAPTIVE_RATIO, Catalog, PriceList, ServiceTier
from seedance_client.validation import VideoRequest

# From the docs' formula: tokens = seconds x width x height x frame rate / 1024.
PIXELS_PER_TOKEN = 1024
PRICE_UNIT_TOKENS = 1_000_000


@dataclass(frozen=True)
class SizeEstimate:
    """Tokens and cost for one output size. cost is None if the price is unknown."""

    ratio: str
    width: int
    height: int
    tokens: Decimal
    cost: Decimal | None


@dataclass(frozen=True)
class Estimate:
    """Cost indication. low equals high unless the ratio is adaptive."""

    request: VideoRequest
    frame_rate: int
    price: Decimal | None
    low: SizeEstimate
    high: SizeEstimate


def make_estimate(request: VideoRequest, catalog: Catalog, prices: PriceList) -> Estimate:
    """Estimate a request that already passed validation."""
    series = catalog.models[request.model].series
    sizes = catalog.sizes[(series, request.resolution)]

    # With an adaptive ratio the API picks the size. The fixed ratios give an
    # indication, not a bound: the real shape may match none of them.
    ratios = list(sizes) if request.ratio == ADAPTIVE_RATIO else [request.ratio]
    price = find_price(request.model, request.resolution, request.service_tier, prices)

    options = []
    for ratio in ratios:
        width, height = sizes[ratio]
        pixels = int(request.duration) * width * height * catalog.frame_rate
        tokens = Decimal(pixels) / PIXELS_PER_TOKEN
        options.append(SizeEstimate(ratio, width, height, tokens, cost_of(tokens, price)))

    options.sort(key=lambda option: option.tokens)
    return Estimate(request, catalog.frame_rate, price, options[0], options[-1])


def find_price(model: str, resolution: str, tier: ServiceTier, prices: PriceList) -> Decimal | None:
    """USD per million tokens, or None if pricing.toml has no such price."""
    return prices.prices.get((model, resolution, tier))


def cost_of(tokens: Decimal | int, price: Decimal | None) -> Decimal | None:
    """Cost in USD, or None if the price is unknown."""
    if price is None:
        return None
    return Decimal(tokens) * price / PRICE_UNIT_TOKENS
