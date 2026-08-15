"""P-04 — development must not be able to address production.

`data-center` publishes 0.0.0.0:5432 on this host; `data-center-test` publishes
5433. One mistyped digit points a hot-reloading development server, with DEBUG
on and migrations pending, at a decade of real financial data. Nothing would
warn, because every layer below would simply do as it was told.

This is the layer that says no.
"""

from __future__ import annotations

import pytest

from config.settings.guards import (
    ConfigurationRefused,
    assert_development_database,
)

PERMITTED = {"financial_hub_dev", "financial_hub_ci"}


def test_the_ordinary_development_configuration_is_accepted():
    assert_development_database("financial_hub_dev", "5433", PERMITTED)


def test_the_tmpfs_test_instance_is_accepted():
    assert_development_database("financial_hub_ci", 5434, PERMITTED)


def test_the_production_database_name_is_refused():
    with pytest.raises(ConfigurationRefused, match="production database"):
        assert_development_database("financial_hub", "5433", PERMITTED)


def test_the_production_port_is_refused_even_with_a_development_name():
    """The likeliest form of the mistake: the right database on the wrong port."""
    with pytest.raises(ConfigurationRefused, match="data-center"):
        assert_development_database("financial_hub_dev", "5432", PERMITTED)


def test_the_port_is_compared_as_a_string_or_an_integer():
    with pytest.raises(ConfigurationRefused):
        assert_development_database("financial_hub_dev", 5432, PERMITTED)


def test_an_unrecognised_database_is_refused():
    with pytest.raises(ConfigurationRefused, match="not a database"):
        assert_development_database("someone_elses_db", "5433", PERMITTED)


def test_the_running_configuration_passed_its_own_guard(settings):
    """Belt and braces: the suite itself is not addressing production."""
    assert settings.DATABASES["default"]["NAME"] != "financial_hub"
    assert str(settings.DATABASES["default"]["PORT"]) != "5432"
