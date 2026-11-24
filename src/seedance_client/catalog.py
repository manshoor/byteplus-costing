"""Loads the dated data files (model limits and prices) into typed objects."""

import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import cache
from importlib import resources
from typing import Any

ADAPTIVE_RATIO = "adaptive"


class Mode(StrEnum):
    """What the video is made from."""

    TEXT = "text"
    IMAGE = "image"


class ServiceTier(StrEnum):
    """Online (default) or offline at half price (flex)."""

    DEFAULT = "default"
    FLEX = "flex"


@dataclass(frozen=True)
class Model:
    """Limits of one model."""

    model_id: str
    series: str
    resolutions: tuple[str, ...]
    min_duration: int
    max_duration: int
    offline_tier: bool


@dataclass(frozen=True)
class Catalog:
    """All model limits and output sizes."""

    read_on: date
    source_urls: tuple[str, ...]
    frame_rate: int
    models: dict[str, Model]
    ratios: dict[tuple[str, Mode], tuple[str, ...]]
    # (series, resolution) -> ratio -> (width, height)
    sizes: dict[tuple[str, str], dict[str, tuple[int, int]]]


@dataclass(frozen=True)
class PriceList:
    """Prices in USD per million tokens, keyed by (model, resolution, tier)."""

    read_on: date
    source_url: str
    prices: dict[tuple[str, str, ServiceTier], Decimal]


def _read_toml(name: str) -> dict[str, Any]:
    # Prices load as Decimal, so money sums stay exact.
    text = resources.files("seedance_client").joinpath("data", name).read_text("utf-8")
    return tomllib.loads(text, parse_float=Decimal)


@cache
def load_catalog() -> Catalog:
    """Read models.toml once."""
    raw = _read_toml("models.toml")

    models = {
        model_id: Model(
            model_id=model_id,
            series=item["series"],
            resolutions=tuple(item["resolutions"]),
            min_duration=item["min_duration"],
            max_duration=item["max_duration"],
            offline_tier=item["offline_tier"],
        )
        for model_id, item in raw["models"].items()
    }

    ratios = {
        (series, mode): tuple(by_mode[mode])
        for series, by_mode in raw["ratios"].items()
        for mode in Mode
    }

    sizes = {
        (series, resolution): {ratio: (size[0], size[1]) for ratio, size in by_ratio.items()}
        for series, by_resolution in raw["sizes"].items()
        for resolution, by_ratio in by_resolution.items()
    }

    return Catalog(
        read_on=raw["read_on"],
        source_urls=tuple(raw["source_urls"]),
        frame_rate=raw["frame_rate"],
        models=models,
        ratios=ratios,
        sizes=sizes,
    )


@cache
def load_prices() -> PriceList:
    """Read pricing.toml once."""
    raw = _read_toml("pricing.toml")
    tables = {ServiceTier.DEFAULT: "online", ServiceTier.FLEX: "offline"}

    # A missing table or entry means "price unknown".
    prices = {
        (model_id, resolution, tier): price
        for model_id, item in raw["models"].items()
        for tier, table in tables.items()
        for resolution, price in item.get(table, {}).items()
    }

    return PriceList(read_on=raw["read_on"], source_url=raw["source_url"], prices=prices)
