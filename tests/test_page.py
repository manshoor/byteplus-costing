"""The explainer page must hold the same data as the tool."""

import json
import re
from pathlib import Path

from seedance_client import client, pricing
from seedance_client.catalog import ADAPTIVE_RATIO, ServiceTier, load_catalog, load_prices

PAGE = Path(__file__).parent.parent / "docs" / "how-it-works.html"
DATA_BLOCK = re.compile(r'<script type="application/json" id="data">(.*?)</script>', re.DOTALL)


def tier_prices(model, tier):
    prices = load_prices().prices
    found = {name: prices.get((model.model_id, name, tier)) for name in model.resolutions}
    return {name: str(price) for name, price in found.items() if price is not None}


def expected_data():
    catalog = load_catalog()
    models = {
        model.model_id: {
            "series": model.series,
            "min": model.min_duration,
            "max": model.max_duration,
            "resolutions": list(model.resolutions),
            "online": tier_prices(model, ServiceTier.DEFAULT),
            "offline": tier_prices(model, ServiceTier.FLEX),
        }
        for model in catalog.models.values()
    }
    sizes = {}
    for (series, resolution), by_ratio in catalog.sizes.items():
        boxes = {ratio: list(size) for ratio, size in by_ratio.items()}
        sizes.setdefault(series, {})[resolution] = boxes
    ratios = [r for r in catalog.ratios[("2.0", "text")] if r != ADAPTIVE_RATIO]
    return {
        "readOn": load_prices().read_on.isoformat(),
        "sourceUrl": load_prices().source_url,
        "frameRate": catalog.frame_rate,
        "pixelsPerToken": pricing.PIXELS_PER_TOKEN,
        "priceUnit": pricing.PRICE_UNIT_TOKENS,
        "poll": {
            "first": client._FIRST_POLL_DELAY,
            "growth": client._POLL_GROWTH,
            "max": client._MAX_POLL_DELAY,
            "limit": client.DEFAULT_WAIT_TIMEOUT,
        },
        "ratios": ratios,
        "models": models,
        "sizes": sizes,
    }


def test_page_data_matches_tool():
    found = DATA_BLOCK.search(PAGE.read_text("utf-8"))
    assert found is not None
    assert json.loads(found[1]) == expected_data()


def test_page_loads_nothing():
    text = PAGE.read_text("utf-8")
    for pattern in (r"\ssrc=", r"<link", r"@import", r"url\(", r"fetch\(", r"XMLHttpRequest"):
        assert re.search(pattern, text) is None, pattern
