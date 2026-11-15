"""Tests for the option inputs offered in Settings → Navidrome → Configure."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.navidrome.config_flow import _int_selector
from custom_components.navidrome.const import (
    CONTROL_GRACE_SECONDS_RANGE,
    DEFAULT_CONTROL_GRACE_SECONDS,
    DEFAULT_PLAYLIST_CACHE_TTL,
    DEFAULT_SEARCH_RESULT_LIMIT,
    PLAYLIST_CACHE_TTL_RANGE,
    SEARCH_RESULT_LIMIT_RANGE,
)


@pytest.mark.parametrize(
    ("bounds", "default", "unit"),
    [
        (SEARCH_RESULT_LIMIT_RANGE, DEFAULT_SEARCH_RESULT_LIMIT, None),
        (PLAYLIST_CACHE_TTL_RANGE, DEFAULT_PLAYLIST_CACHE_TTL, "s"),
        (CONTROL_GRACE_SECONDS_RANGE, DEFAULT_CONTROL_GRACE_SECONDS, "s"),
    ],
)
def test_selector_accepts_default_and_bounds(bounds, default, unit) -> None:
    """Each option's default and its min/max are valid inputs."""
    selector = _int_selector(bounds, unit=unit)

    assert selector(default) == default
    assert selector(bounds[0]) == bounds[0]
    assert selector(bounds[1]) == bounds[1]


@pytest.mark.parametrize(
    "bounds", [SEARCH_RESULT_LIMIT_RANGE, PLAYLIST_CACHE_TTL_RANGE, CONTROL_GRACE_SECONDS_RANGE]
)
def test_selector_rejects_out_of_range(bounds) -> None:
    """Values outside (min, max) are rejected."""
    selector = _int_selector(bounds)

    with pytest.raises(vol.Invalid):
        selector(bounds[0] - 1)
    with pytest.raises(vol.Invalid):
        selector(bounds[1] + 1)


def test_unit_only_set_when_given() -> None:
    """unit_of_measurement is omitted (not None) when no unit is passed."""
    assert "unit_of_measurement" not in _int_selector((0, 10)).config
    assert _int_selector((0, 10), unit="s").config["unit_of_measurement"] == "s"
