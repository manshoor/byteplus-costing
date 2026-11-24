from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from seedance_client.catalog import ServiceTier, load_catalog, load_prices
from seedance_client.pricing import make_estimate
from seedance_client.validation import VideoRequest

PRO_25 = "dreamina-seedance-2-5-260628"
FLASH_25 = "dreamina-seedance-2-5-flash-261115"
PRO_20 = "dreamina-seedance-2-0-260128"
FAST_20 = "dreamina-seedance-2-0-fast-260128"
MINI_20 = "dreamina-seedance-2-0-mini-260615"
PRO_10 = "seedance-1-0-pro-250528"
FAST_10 = "seedance-1-0-pro-fast-251015"

# The docs' own examples: 16:9, 5 seconds.
DOCS_COSTS = [
    (PRO_25, "480p", "0.514"),
    (PRO_25, "720p", "1.156"),
    (PRO_25, "1080p", "2.843"),
    (PRO_25, "4k", "4.568"),
    (FLASH_25, "480p", "0.34"),
    (FLASH_25, "720p", "0.76"),
    (PRO_20, "480p", "0.35"),
    (PRO_20, "720p", "0.76"),
    (PRO_20, "1080p", "1.87"),
    (PRO_20, "4k", "3.89"),
    (FAST_20, "480p", "0.28"),
    (FAST_20, "720p", "0.60"),
    (MINI_20, "480p", "0.18"),
    (MINI_20, "720p", "0.38"),
    (PRO_10, "480p", "0.12"),
    (PRO_10, "720p", "0.26"),
    (PRO_10, "1080p", "0.61"),
    (FAST_10, "480p", "0.05"),
    (FAST_10, "720p", "0.10"),
    (FAST_10, "1080p", "0.24"),
]


def estimate(model, resolution, ratio="16:9", duration=5, **fields):
    request = VideoRequest(model, resolution, ratio, duration, **fields)
    return make_estimate(request, load_catalog(), load_prices())


@pytest.mark.parametrize(("model", "resolution", "docs_cost"), DOCS_COSTS)
def test_cost_matches_docs(model, resolution, docs_cost):
    expected = Decimal(docs_cost)
    assert estimate(model, resolution).low.cost.quantize(expected) == expected


@pytest.mark.parametrize(
    ("resolution", "duration", "tokens"),
    # The 10 s docs example says 97,000; the formula gives 97,200 (API_NOTES, section 12).
    [("480p", 5, 48_600), ("720p", 5, 102_960), ("1080p", 5, 244_800), ("480p", 10, 97_200)],
)
def test_tokens_match_formula(resolution, duration, tokens):
    assert estimate(PRO_10, resolution, duration=duration).low.tokens == tokens


def test_tokens_keep_fractions():
    assert estimate(PRO_25, "480p").low.tokens == Decimal("48037.5")


@pytest.mark.parametrize("model", [PRO_10, FAST_10])
def test_flex_is_half_price(model):
    online = estimate(model, "1080p").low.cost
    offline = estimate(model, "1080p", service_tier=ServiceTier.FLEX).low.cost
    assert offline * 2 == online


def test_missing_price_is_unknown():
    prices = replace(load_prices(), prices={})
    request = VideoRequest(PRO_10, "480p", "16:9", 5)
    result = make_estimate(request, load_catalog(), prices)
    assert result.price is None
    assert result.low.cost is None
    assert result.low.tokens == 48_600


def test_fixed_ratio_has_no_range():
    result = estimate(PRO_20, "720p")
    assert result.low == result.high


def test_adaptive_gives_a_range():
    result = estimate(PRO_20, "480p", ratio="adaptive")
    fixed = ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9")
    costs = [estimate(PRO_20, "480p", ratio=ratio).low.cost for ratio in fixed]
    assert (result.low.cost, result.high.cost) == (min(costs), max(costs))
    assert result.low.cost < result.high.cost


# Width and height from the pixel table in docs/API_NOTES.md, for each series.
@pytest.mark.parametrize(
    ("model", "resolution", "ratio", "width", "height"),
    [
        (PRO_25, "480p", "9:16", 480, 854),
        (PRO_25, "720p", "21:9", 1470, 630),
        (PRO_25, "4k", "3:4", 2494, 3326),
        (PRO_20, "480p", "9:16", 496, 864),
        (PRO_20, "720p", "4:3", 1112, 834),
        (PRO_20, "1080p", "21:9", 2206, 946),
        (PRO_10, "480p", "4:3", 736, 544),
        (PRO_10, "720p", "1:1", 960, 960),
        (PRO_10, "1080p", "9:16", 1088, 1920),
    ],
)
def test_size_matches_docs(model, resolution, ratio, width, height):
    size = estimate(model, resolution, ratio).low
    assert (size.width, size.height) == (width, height)
    assert size.tokens == Decimal(5 * width * height * 24) / 1024


@pytest.mark.parametrize(("series", "column"), [("2.5", 3), ("2.0", 4), ("1.0", 5)])
def test_sizes_match_notes(series, column):
    # Reads the whole documented table, so one wrong number in models.toml fails.
    notes = Path(__file__).parent.parent / "docs" / "API_NOTES.md"
    rows = [line.split("|") for line in notes.read_text("utf-8").splitlines()]
    sizes = load_catalog().sizes
    found = 0
    for row in rows:
        cells = [cell.strip() for cell in row]
        if len(cells) != 7 or cells[1] not in ("480p", "720p", "1080p", "4k"):
            continue
        if "×" not in cells[column]:
            continue
        expected = tuple(int(number) for number in cells[column].split("×"))
        assert sizes[(series, cells[1])][cells[2]] == expected
        found += 1
    assert found == sum(len(by) for (name, _), by in sizes.items() if name == series)
