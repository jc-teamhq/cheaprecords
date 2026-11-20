"""Tests for the command-line entry point."""

import json
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

import httpx
import pytest

from cheaprecords import __version__
from cheaprecords.__main__ import main
from cheaprecords.jbhifi import JBHiFiError

SHOP = "http://shop.test"
API = "http://api.test"
REISSUE = f"{SHOP}/products/vinyl-coltrane-john-a-love-supreme-lp"
BLUE_TRAIN = f"{SHOP}/products/vinyl-coltrane-john-blue-train-lp"
GONE = f"{SHOP}/products/vinyl-coltrane-john-gone-lp"
DEALS = f"{SHOP}/collections/clearance"


class Browser:
    """A fake browser serving the pages it is given."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def fetch(self, url: str, *, wait_for: str | None = None) -> str:
        del wait_for
        if url not in self.pages:
            message = f"{url} returned HTTP 404"
            raise JBHiFiError(message)
        return self.pages[url]


def network(request: httpx.Request) -> httpx.Response:
    """A fake JB Hi-Fi sitemap and Discogs API."""
    path = request.url.path
    if path == "/sitemap.xml":
        loc = f"{SHOP}/sitemap_products_1.xml"
        return httpx.Response(200, text=f"<loc>{loc}</loc>")
    if path == "/sitemap_products_1.xml":
        locs = "".join(f"<loc>{url}</loc>" for url in (REISSUE, BLUE_TRAIN, GONE))
        return httpx.Response(200, text=locs)
    if path == "/database/search":
        release = {"11105015516": 1, "222": 2}[request.url.params["barcode"]]
        return httpx.Response(200, json={"results": [{"id": release}]})
    if path.endswith("/rating"):
        return httpx.Response(200, json={"rating": {"count": 81, "average": 4.79}})
    low = {"/marketplace/stats/1": 29.41, "/marketplace/stats/2": 45.0}[path]
    return httpx.Response(200, json={"num_for_sale": 4, "lowest_price": {"value": low}})


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("CHEAPRECORDS_JBHIFI_URL", SHOP)
    monkeypatch.setenv("CHEAPRECORDS_DISCOGS_URL", API)
    monkeypatch.delenv("CHEAPRECORDS_JBHIFI_DEALS_URL", raising=False)
    monkeypatch.delenv("DISCOGS_TOKEN", raising=False)
    monkeypatch.setattr("cheaprecords.jbhifi.SITEMAP_DELAY", 0)


@pytest.fixture
def run(product_page: Callable[..., str]) -> Callable[..., int]:
    """Run the CLI against the fake network and a fake browser."""
    pages = {
        REISSUE: product_page(),
        BLUE_TRAIN: product_page(name="Blue Train", price="20.00", gtin="222"),
        DEALS: f'<a href="/products/{BLUE_TRAIN.rsplit("/", 1)[-1]}">Blue Train</a>',
    }

    def run(
        *argv: str,
        handler: Callable[[httpx.Request], httpx.Response] = network,
    ) -> int:
        return main(
            argv,
            transport=httpx.MockTransport(handler),
            browser=lambda: Browser(pages),
        )

    return run


def test_search_compares_matches_best_first(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("coltrane", "john") == 0
    captured = capsys.readouterr()
    rows = captured.out.splitlines()
    assert rows[0].split()[0] == "Record"
    assert rows[1].startswith("JOHN COLTRANE - Blue Train")
    assert rows[1].endswith("-25.00")
    assert rows[2].startswith("JOHN COLTRANE - A Love Supreme")
    assert rows[2].endswith("+75.59")
    assert "negative means JB Hi-Fi is cheaper" in rows[-1]
    assert "[1/3] vinyl-coltrane-john-gone-lp" in captured.err
    assert "skipped: " in captured.err


def test_product_urls_skip_the_search(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(REISSUE, "--json") == 0
    captured = capsys.readouterr()
    (only,) = json.loads(captured.out)
    assert only["record"]["url"] == REISSUE
    assert only["difference"] == 75.59
    assert "Indexing" not in captured.err


def test_urls_and_words_combine_without_duplicates(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(REISSUE, "supreme", "--json") == 0
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_limit_caps_the_search(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    # Newest first: the withdrawn record (skipped), then Blue Train.
    assert run("coltrane", "--limit", "2", "--json") == 0
    (only,) = json.loads(capsys.readouterr().out)
    assert only["record"]["title"] == "Blue Train"


def test_no_query_compares_the_newest_additions(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    # The sitemap lists the withdrawn record last, so it is the newest.
    assert run("--limit", "2", "--json") == 0
    captured = capsys.readouterr()
    assert "[1/2] vinyl-coltrane-john-gone-lp" in captured.err
    assert "[2/2] vinyl-coltrane-john-blue-train-lp" in captured.err
    assert [item["record"]["title"] for item in json.loads(captured.out)] == [
        "Blue Train"
    ]


def test_deals_compares_the_records_on_the_deals_page(
    run: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CHEAPRECORDS_JBHIFI_DEALS_URL", DEALS)
    assert run("--deals", "--json") == 0
    captured = capsys.readouterr()
    (only,) = json.loads(captured.out)
    assert only["record"]["title"] == "Blue Train"
    assert only["difference"] == -25.0
    assert "Indexing" not in captured.err


def test_deals_needs_the_deals_page_address(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("--deals") == 1
    assert (
        "CHEAPRECORDS_JBHIFI_DEALS_URL must be set to use --deals"
        in capsys.readouterr().err
    )


def test_deals_cannot_be_combined_with_a_query(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        run("--deals", "coltrane")
    assert exc_info.value.code == 2
    assert "--deals cannot be combined with a query" in capsys.readouterr().err


def test_no_match_exits_with_an_error(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("zappa") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "No JB Hi-Fi vinyl found to compare." in captured.err


def test_service_failure_exits_with_an_error(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    def down(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert run(REISSUE, handler=down) == 1
    assert "error: Discogs returned HTTP 503" in capsys.readouterr().err


def test_each_site_is_asked_at_its_configured_address(
    run: Callable[..., int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISCOGS_TOKEN", "placeholder")
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return network(request)

    assert run("supreme", handler=recording) == 0
    assert {request.url.host for request in seen} == {"shop.test", "api.test"}
    for request in seen:
        sent = request.headers.get("Authorization")
        expected = (
            "Discogs token=placeholder" if request.url.host == "api.test" else None
        )
        assert sent == expected


def test_address_outside_the_storefront_is_refused(
    run: Callable[..., int], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("http://elsewhere.test/products/vinyl-x") == 1
    assert "not a JB Hi-Fi product page" in capsys.readouterr().err


def test_missing_addresses_exit_with_an_error(
    run: Callable[..., int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CHEAPRECORDS_JBHIFI_URL")
    assert run("coltrane") == 1
    assert "CHEAPRECORDS_JBHIFI_URL must be set" in capsys.readouterr().err


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    prog = "cheaprecords"
    assert capsys.readouterr().out == f"{prog} {__version__}\n"
