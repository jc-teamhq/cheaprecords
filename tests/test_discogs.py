"""Tests for the Discogs client."""

from collections.abc import Callable

import httpx
import pytest

from cheaprecords.cache import Cache
from cheaprecords.discogs import Discogs, DiscogsError, Market

API = "http://api.test"
# Stands in for a Discogs token; not a real credential.
PLACEHOLDER = "placeholder"

STATS = {
    "/marketplace/stats/1": {"num_for_sale": 12, "lowest_price": {"value": 29.41}},
    "/marketplace/stats/2": {"num_for_sale": 3, "lowest_price": {"value": 34.26}},
    "/marketplace/stats/3": {"num_for_sale": 0, "lowest_price": None},
    "/marketplace/stats/4": {"num_for_sale": 9, "lowest_price": {"value": 62.52}},
}


# How many collectors own each release, and how they rate it.
OWNERS = {1: 12, 2: 1666, 3: 5, 4: 40}
RATINGS = {
    "/releases/1/rating": {"rating": {"count": 81, "average": 4.79}},
    "/releases/2/rating": {"rating": {"count": 593, "average": 4.67}},
    "/releases/3/rating": {"rating": {"count": 0, "average": 0}},
    "/releases/4/rating": {"rating": {"count": 9, "average": 4.11}},
}


class Api:
    """A fake Discogs API that records requests and can be told to misbehave."""

    def __init__(self, release_ids: list[int], total: int | None = None) -> None:
        self.search = {
            "pagination": {"items": len(release_ids) if total is None else total},
            "results": [
                {"id": release_id, "community": {"have": OWNERS[release_id]}}
                for release_id in release_ids
            ],
        }
        self.requests: list[httpx.Request] = []
        self.queued: list[httpx.Response] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.queued:
            return self.queued.pop(0)
        if request.url.path == "/database/search":
            return httpx.Response(200, json=self.search)
        if request.url.path in RATINGS:
            return httpx.Response(200, json=RATINGS[request.url.path])
        return httpx.Response(200, json=STATS[request.url.path])


class Waits:
    """Records how long the client asked to sleep."""

    def __init__(self) -> None:
        self.seconds: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def client_for(
    api: Api,
    cache: Cache,
    *,
    token: str | None = None,
    progress: Callable[[str], None] = lambda _: None,
    sleep: Callable[[float], None] = lambda _: None,
) -> Discogs:
    client = httpx.Client(base_url=API, transport=httpx.MockTransport(api))
    return Discogs(client, cache, token=token, progress=progress, sleep=sleep)


def test_market_summarises_the_pressings(cache: Cache) -> None:
    api = Api([1, 2, 3, 4])
    assert client_for(api, cache).market("11105015516", max_pressings=5) == Market(
        pressings=4,
        checked=4,
        for_sale=24,
        lowest=29.41,
        median=34.26,
        rating=4.67,
        votes=593,
    )
    search = api.requests[0].url
    assert search.host == "api.test"
    assert search.path == "/database/search"
    assert dict(search.params) == {
        "barcode": "11105015516",
        "type": "release",
        "format": "Vinyl",
    }
    assert api.requests[1].url.params["curr_abbr"] == "AUD"


def test_market_prices_at_most_max_pressings(cache: Cache) -> None:
    api = Api([1, 2, 3, 4], total=19)
    market = client_for(api, cache).market("11105015516", max_pressings=2)
    assert market == Market(
        pressings=19,
        checked=2,
        for_sale=15,
        lowest=29.41,
        median=31.835,
        rating=4.67,
        votes=593,
    )
    assert [request.url.path for request in api.requests] == [
        "/database/search",
        "/marketplace/stats/1",
        "/marketplace/stats/2",
        "/releases/2/rating",
    ]


def test_rating_comes_from_the_most_collected_pressing(cache: Cache) -> None:
    # Release 4 is not among the pressings priced, but more people own it.
    market = client_for(Api([1, 3, 4]), cache).market("11105015516", max_pressings=2)
    assert market is not None
    assert (market.rating, market.votes) == (4.11, 9)


def test_market_with_nothing_for_sale(cache: Cache) -> None:
    market = client_for(Api([3]), cache).market("11105015516", max_pressings=5)
    assert market == Market(
        pressings=1,
        checked=1,
        for_sale=0,
        lowest=None,
        median=None,
        rating=None,
        votes=0,
    )


def test_market_is_none_for_an_unknown_barcode(cache: Cache) -> None:
    assert client_for(Api([]), cache).market("000", max_pressings=5) is None


def test_responses_are_cached(cache: Cache) -> None:
    api = Api([1, 2])
    first = client_for(api, cache).market("11105015516", max_pressings=5)
    calls = len(api.requests)
    assert client_for(api, cache).market("11105015516", max_pressings=5) == first
    assert len(api.requests) == calls


def test_token_is_sent_when_given(cache: Cache) -> None:
    api = Api([1])
    client_for(api, cache, token=PLACEHOLDER).market("11105015516", max_pressings=5)
    assert api.requests[0].headers["Authorization"] == "Discogs token=placeholder"


def test_no_authorization_without_a_token(cache: Cache) -> None:
    api = Api([1])
    client_for(api, cache).market("11105015516", max_pressings=5)
    assert "Authorization" not in api.requests[0].headers


def test_waits_when_the_rate_limit_runs_out(cache: Cache) -> None:
    api = Api([1])
    api.queued.append(
        httpx.Response(
            200, json=api.search, headers={"X-Discogs-Ratelimit-Remaining": "0"}
        )
    )
    waits = Waits()
    messages: list[str] = []
    discogs = client_for(api, cache, sleep=waits, progress=messages.append)
    assert discogs.market("11105015516", max_pressings=5) is not None
    assert waits.seconds == [60.0]
    assert messages == ["Discogs rate limit reached; waiting 60s"]


def test_retries_after_too_many_requests(cache: Cache) -> None:
    api = Api([1])
    api.queued.append(httpx.Response(429))
    waits = Waits()
    market = client_for(api, cache, sleep=waits).market("11105015516", max_pressings=5)
    assert market is not None
    assert market.lowest == 29.41
    assert waits.seconds == [60.0]


def test_gives_up_when_the_rate_limit_never_clears(cache: Cache) -> None:
    api = Api([1])
    api.queued.extend(httpx.Response(429) for _ in range(3))
    with pytest.raises(DiscogsError, match="rate limit"):
        client_for(api, cache, sleep=Waits()).market("11105015516", max_pressings=5)


def test_error_status_is_reported(cache: Cache) -> None:
    api = Api([1])
    api.queued.append(httpx.Response(401))
    with pytest.raises(DiscogsError, match="HTTP 401"):
        client_for(api, cache).market("11105015516", max_pressings=5)


def test_network_failure_is_reported(cache: Cache) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        message = "connection refused"
        raise httpx.ConnectError(message, request=request)

    client = httpx.Client(base_url=API, transport=httpx.MockTransport(unreachable))
    with pytest.raises(DiscogsError, match="could not reach Discogs"):
        Discogs(client, cache).market("11105015516", max_pressings=5)
