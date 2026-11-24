from datetime import date
from decimal import Decimal

from seedance_client.catalog import ADAPTIVE_RATIO, Mode, load_catalog, load_prices

READ_ON = date(2026, 11, 23)


def test_files_are_dated():
    assert load_catalog().read_on == READ_ON
    assert load_prices().read_on == READ_ON


def test_every_option_has_a_size():
    catalog = load_catalog()
    for model in catalog.models.values():
        for resolution in model.resolutions:
            for mode in Mode:
                for ratio in catalog.ratios[(model.series, mode)]:
                    if ratio != ADAPTIVE_RATIO:
                        assert ratio in catalog.sizes[(model.series, resolution)]


def test_every_option_has_a_price():
    prices = load_prices().prices
    for model in load_catalog().models.values():
        for resolution in model.resolutions:
            assert isinstance(prices[(model.model_id, resolution, "default")], Decimal)
            assert ((model.model_id, resolution, "flex") in prices) == model.offline_tier
