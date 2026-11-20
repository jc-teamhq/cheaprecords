"""Tests for reading settings from the environment."""

import pytest

from cheaprecords.config import Config, ConfigError, load_config

# Stands in for a Discogs token; not a real credential.
PLACEHOLDER = "placeholder"

ADDRESSES = {
    "CHEAPRECORDS_JBHIFI_URL": "http://shop.test",
    "CHEAPRECORDS_DISCOGS_URL": "http://api.test",
}


def test_reads_both_addresses() -> None:
    assert load_config(ADDRESSES) == Config(
        jbhifi_url="http://shop.test",
        discogs_url="http://api.test",
        jbhifi_deals_url=None,
        discogs_token=None,
    )


def test_reads_the_deals_page_when_set() -> None:
    deals = "http://shop.test/collections/clearance"
    config = load_config({**ADDRESSES, "CHEAPRECORDS_JBHIFI_DEALS_URL": deals})
    assert config.jbhifi_deals_url == deals


def test_reads_the_token_when_set() -> None:
    config = load_config({**ADDRESSES, "DISCOGS_TOKEN": PLACEHOLDER})
    assert config.discogs_token == PLACEHOLDER


def test_empty_token_counts_as_unset() -> None:
    assert load_config({**ADDRESSES, "DISCOGS_TOKEN": ""}).discogs_token is None


def test_names_every_missing_address() -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_config({"CHEAPRECORDS_JBHIFI_URL": ""})
    assert str(exc_info.value) == (
        "CHEAPRECORDS_JBHIFI_URL and CHEAPRECORDS_DISCOGS_URL must be set; "
        "see the README"
    )


def test_reads_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in ADDRESSES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DISCOGS_TOKEN", PLACEHOLDER)
    assert load_config().discogs_token == PLACEHOLDER
