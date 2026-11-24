from dataclasses import replace

import pytest

from seedance_client.catalog import ServiceTier, load_catalog
from seedance_client.validation import (
    VideoRequest,
    find_problems,
    find_prompt_problems,
    find_warnings,
)

PRO_25 = "dreamina-seedance-2-5-260628"
FLASH_25 = "dreamina-seedance-2-5-flash-261115"
PRO_20 = "dreamina-seedance-2-0-260128"
PRO_10 = "seedance-1-0-pro-250528"
IMAGE = "https://example.com/cat.png"
GOOD = VideoRequest(PRO_10, "480p", "16:9", 5, prompt="A cat")


def problems(**changes):
    return find_problems(replace(GOOD, **changes), load_catalog())


def test_good_request_passes():
    assert problems() == []
    assert find_prompt_problems(GOOD) == []
    assert find_warnings(GOOD) == []


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"model": "nope"}, "Unknown model"),
        ({"resolution": "4k"}, "Resolution"),
        ({"model": FLASH_25, "resolution": "1080p"}, "Resolution"),
        ({"ratio": "2:1"}, "Ratio"),
        ({"ratio": "adaptive"}, "Ratio"),
        ({"model": PRO_25, "image_url": IMAGE}, "Ratio"),
        ({"duration": -1}, "automatic"),
        ({"duration": 0}, "outside 2 to 12"),
        ({"duration": 13}, "outside 2 to 12"),
        ({"duration": "5.5"}, "whole number"),
        ({"duration": True}, "whole number"),
        ({"model": PRO_20, "service_tier": ServiceTier.FLEX}, "flex"),
        ({"image_url": "ftp://example.com/cat.png"}, "image URL"),
        ({"image_url": ""}, "image URL"),
        ({"image_url": "https://"}, "image URL"),
        ({"image_url": "https:///cat.png"}, "image URL"),
        ({"image_url": "https://:80/a"}, "image URL"),
        ({"image_url": "https://[bad"}, "image URL"),
        ({"image_url": "https://a.com/\udcff"}, "image URL"),
    ],
)
def test_each_rule_rejects(changes, words):
    found = problems(**changes)
    assert len(found) == 1
    assert words in found[0]


@pytest.mark.parametrize(
    "changes",
    [
        {"duration": 2},
        {"duration": 12},
        {"service_tier": ServiceTier.FLEX},
        {"image_url": IMAGE, "ratio": "adaptive"},
        {"image_url": IMAGE},
        {"model": PRO_20, "ratio": "adaptive"},
        {"model": PRO_20, "image_url": IMAGE},
        {"model": PRO_20, "resolution": "4k", "duration": 15},
        {"model": PRO_25, "ratio": "adaptive"},
        {"model": PRO_25, "duration": 30},
        {"model": PRO_25, "ratio": "adaptive", "image_url": IMAGE},
    ],
)
def test_allowed_options_pass(changes):
    assert problems(**changes) == []


def test_all_problems_are_listed():
    assert len(problems(resolution="8k", ratio="2:1", duration=99, image_url="x")) == 4


@pytest.mark.parametrize("prompt", [None, "", "   "])
def test_text_mode_needs_a_prompt(prompt):
    assert find_prompt_problems(replace(GOOD, prompt=prompt))
    assert find_prompt_problems(replace(GOOD, prompt=prompt, image_url=IMAGE)) == []


def test_prompt_must_be_utf8():
    assert find_prompt_problems(replace(GOOD, prompt="cat \udcff"))
    assert find_prompt_problems(replace(GOOD, prompt="cat \udcff", image_url=IMAGE))
    assert find_prompt_problems(replace(GOOD, prompt="猫 🐈")) == []


def test_long_prompt_only_warns():
    assert find_warnings(replace(GOOD, prompt="word " * 1000)) == []
    request = replace(GOOD, prompt="word " * 1001)
    assert find_warnings(request)
    assert find_problems(request, load_catalog()) == []
