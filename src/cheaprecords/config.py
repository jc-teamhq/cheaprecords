"""Settings read from the environment.

Nothing about the sites being compared is built in: their addresses, like
the optional Discogs token, are supplied by whoever runs the tool.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

JBHIFI_URL_VARIABLE = "CHEAPRECORDS_JBHIFI_URL"
DISCOGS_URL_VARIABLE = "CHEAPRECORDS_DISCOGS_URL"
JBHIFI_DEALS_URL_VARIABLE = "CHEAPRECORDS_JBHIFI_DEALS_URL"


class ConfigError(Exception):
    """A required setting is missing."""


@dataclass(frozen=True)
class Config:
    """Where to find the two sites, and how to sign in to Discogs."""

    jbhifi_url: str
    """Address of the JB Hi-Fi storefront."""
    discogs_url: str
    """Address of the Discogs API."""
    jbhifi_deals_url: str | None
    """Address of a JB Hi-Fi page listing discounted vinyl, if one is set."""
    discogs_token: str | None
    """A Discogs personal access token, if one is set."""


def load_config(environ: Mapping[str, str] = os.environ) -> Config:
    """Read the settings from environment variables.

    Args:
        environ: The environment to read; defaults to the process's own.

    Returns:
        The settings.

    Raises:
        ConfigError: If either site's address is not set.
    """
    missing = [
        name
        for name in (JBHIFI_URL_VARIABLE, DISCOGS_URL_VARIABLE)
        if not environ.get(name)
    ]
    if missing:
        message = f"{' and '.join(missing)} must be set; see the README"
        raise ConfigError(message)
    return Config(
        jbhifi_url=environ[JBHIFI_URL_VARIABLE],
        discogs_url=environ[DISCOGS_URL_VARIABLE],
        jbhifi_deals_url=environ.get(JBHIFI_DEALS_URL_VARIABLE) or None,
        discogs_token=environ.get("DISCOGS_TOKEN") or None,
    )
