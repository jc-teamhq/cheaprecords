"""Discogs: marketplace prices for the pressings that carry a barcode."""

import json
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from cheaprecords.cache import Cache

CURRENCY = "AUD"
MAX_AGE = timedelta(hours=24)
# Discogs counts requests over a moving window of this many seconds.
RATE_WINDOW = 60.0

_OK = 200
_TOO_MANY_REQUESTS = 429
_ATTEMPTS = 3


class DiscogsError(Exception):
    """Discogs could not be read."""


@dataclass(frozen=True)
class Market:
    """What the Discogs marketplace asks for a record."""

    pressings: int
    """How many Discogs releases carry the barcode."""
    checked: int
    """How many of those pressings were priced."""
    for_sale: int
    """Copies for sale across the pressings checked."""
    lowest: float | None
    """The cheapest listing among the pressings checked, if any are for sale."""
    median: float | None
    """The median of each checked pressing's cheapest listing."""
    rating: float | None
    """The community's average rating, out of 5, of the most collected pressing."""
    votes: int
    """How many ratings that average is drawn from."""


class Discogs:
    """A client for the parts of the Discogs API used to price a record."""

    def __init__(
        self,
        client: httpx.Client,
        cache: Cache,
        *,
        token: str | None = None,
        progress: Callable[[str], None] = lambda _: None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a client.

        Args:
            client: Used to call the API; its `base_url` is the address of
                the Discogs API.
            cache: Where responses are kept between runs.
            token: A Discogs personal access token; optional, but it raises
                the rate limit from 25 to 60 requests a minute.
            progress: Called with a status line when waiting on the rate limit.
            sleep: Waits out the rate limit; replaceable in tests.
        """
        self._client = client
        self._cache = cache
        self._headers = {"Authorization": f"Discogs token={token}"} if token else {}
        self._progress = progress
        self._sleep = sleep
        self._exhausted = False

    def market(self, barcode: str, max_pressings: int) -> Market | None:
        """Price the vinyl pressings that carry a barcode.

        Args:
            barcode: The record's barcode.
            max_pressings: The most pressings to price; each costs a request.
                One more request fetches the rating.

        Returns:
            The marketplace summary, or None if Discogs knows no vinyl
            release with that barcode.

        Raises:
            DiscogsError: If the API cannot be read.
        """
        found = self._get(
            "/database/search",
            {"barcode": barcode, "type": "release", "format": "Vinyl"},
        )
        results = found.get("results", [])
        if not results:
            return None
        release_ids = [result["id"] for result in results]
        checked = release_ids[:max_pressings]
        lows: list[float] = []
        for_sale = 0
        for release_id in checked:
            stats = self._get(
                f"/marketplace/stats/{release_id}", {"curr_abbr": CURRENCY}
            )
            for_sale += stats.get("num_for_sale") or 0
            price = (stats.get("lowest_price") or {}).get("value")
            if price is not None:
                lows.append(float(price))
        # One pressing's rating stands for the record: the one most people
        # own has the most votes, and asking about each would double the calls.
        most_collected = max(
            results, key=lambda result: (result.get("community") or {}).get("have", 0)
        )
        rating = (
            self._get(f"/releases/{most_collected['id']}/rating", {}).get("rating")
            or {}
        )
        votes = rating.get("count") or 0
        return Market(
            pressings=found.get("pagination", {}).get("items", len(release_ids)),
            checked=len(checked),
            for_sale=for_sale,
            lowest=min(lows, default=None),
            median=statistics.median(lows) if lows else None,
            rating=float(rating["average"]) if votes else None,
            votes=votes,
        )

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        query = urlencode(sorted(params.items()))
        key = f"{self._client.base_url.join(path)}?{query}"
        cached = self._cache.get("discogs", key, MAX_AGE)
        if cached is not None:
            return json.loads(cached)
        for _ in range(_ATTEMPTS):
            if self._exhausted:
                self._progress(
                    f"Discogs rate limit reached; waiting {RATE_WINDOW:.0f}s"
                )
                self._sleep(RATE_WINDOW)
            try:
                response = self._client.get(path, params=params, headers=self._headers)
            except httpx.HTTPError as exc:
                message = f"could not reach Discogs: {exc}"
                raise DiscogsError(message) from exc
            self._exhausted = (
                response.status_code == _TOO_MANY_REQUESTS
                or response.headers.get("X-Discogs-Ratelimit-Remaining") == "0"
            )
            if response.status_code == _TOO_MANY_REQUESTS:
                continue
            if response.status_code != _OK:
                message = f"Discogs returned HTTP {response.status_code} for {path}"
                raise DiscogsError(message)
            self._cache.put("discogs", key, response.text)
            return response.json()
        message = "Discogs rate limit still exceeded after waiting"
        raise DiscogsError(message)
