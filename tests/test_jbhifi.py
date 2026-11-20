"""Tests for reading JB Hi-Fi's sitemap and product pages."""

from collections.abc import Callable

import httpx
import pytest

from cheaprecords.cache import Cache
from cheaprecords.jbhifi import (
    Catalogue,
    JBHiFiError,
    Record,
    load_record,
    parse_product,
)

SHOP = "http://shop.test"
PRODUCT_URL = f"{SHOP}/products/vinyl-coltrane-john-a-love-supreme-lp"

SITEMAP_INDEX = """<sitemapindex>
  <sitemap><loc>http://shop.test/sitemap_products_1.xml?from=1&amp;to=2</loc></sitemap>
  <sitemap><loc>http://shop.test/sitemap_products_2.xml?from=3&amp;to=4</loc></sitemap>
  <sitemap><loc>http://shop.test/sitemap_collections_1.xml</loc></sitemap>
</sitemapindex>"""

SITEMAPS = {
    "/sitemap.xml": SITEMAP_INDEX,
    "/sitemap_products_1.xml": """<urlset>
      <url><loc>http://shop.test/products/vinyl-coltrane-john-a-love-supreme-lp</loc></url>
      <url><loc>http://shop.test/products/cd-coltrane-john-a-love-supreme-cd</loc></url>
      <url><loc>http://shop.test/products/vinyl-beyonce-lemonade-2lp</loc></url>
    </urlset>""",
    "/sitemap_products_2.xml": """<urlset>
      <url><loc>http://shop.test/products/lenoxx-vinyl-turntable</loc></url>
      <url><loc>http://shop.test/products/vinyl-coltrane-john-a-love-supreme-reissue-lp</loc></url>
      <url><loc>http://shop.test/products/vinyl-crowded-house-dont-dream-its-over-lp</loc></url>
    </urlset>""",
}


class Site:
    """A fake JB Hi-Fi serving sitemaps and counting the requests."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path not in self.pages:
            return httpx.Response(404)
        return httpx.Response(200, text=self.pages[request.url.path])


def client_for(site: Site) -> httpx.Client:
    return httpx.Client(base_url=SHOP, transport=httpx.MockTransport(site))


def catalogue_for(site: Site, cache: Cache) -> Catalogue:
    return Catalogue(client_for(site), cache, sleep=lambda _: None)


class Pages:
    """A fake browser returning one page and counting the loads."""

    def __init__(self, page_html: str) -> None:
        self.page_html = page_html
        self.loaded: list[str] = []
        self.waited_for: list[str | None] = []

    def fetch(self, url: str, *, wait_for: str | None = None) -> str:
        self.loaded.append(url)
        self.waited_for.append(wait_for)
        return self.page_html


def test_parse_product(product_page: Callable[..., str]) -> None:
    assert parse_product(product_page(), PRODUCT_URL) == Record(
        title="A Love Supreme",
        artist="JOHN COLTRANE",
        price=105.0,
        barcode="11105015516",
        url=PRODUCT_URL,
        in_stock=True,
    )


def test_parse_product_out_of_stock_without_barcode(
    product_page: Callable[..., str],
) -> None:
    page = product_page(gtin=None, availability="OutOfStock")
    record = parse_product(page, PRODUCT_URL)
    assert record.barcode is None
    assert not record.in_stock


def test_parse_product_without_product_data() -> None:
    with pytest.raises(JBHiFiError, match="no product data"):
        parse_product("<html><body>Too many requests</body></html>", PRODUCT_URL)


@pytest.mark.parametrize("price", [None, "call us"])
def test_parse_product_without_usable_price(
    product_page: Callable[..., str], price: str | None
) -> None:
    with pytest.raises(JBHiFiError, match="no price"):
        parse_product(product_page(price=price), PRODUCT_URL)


def test_load_record_loads_the_page_once(
    product_page: Callable[..., str], cache: Cache
) -> None:
    pages = Pages(product_page())
    first = load_record(PRODUCT_URL, pages, cache)
    second = load_record(PRODUCT_URL, pages, cache)
    assert first == second
    assert first.price == 105.0
    assert pages.loaded == [PRODUCT_URL]


def test_slugs_lists_only_vinyl(cache: Cache) -> None:
    messages: list[str] = []
    catalogue = Catalogue(
        client_for(Site(SITEMAPS)),
        cache,
        progress=messages.append,
        sleep=lambda _: None,
    )
    assert catalogue.slugs() == [
        "vinyl-coltrane-john-a-love-supreme-lp",
        "vinyl-beyonce-lemonade-2lp",
        "vinyl-coltrane-john-a-love-supreme-reissue-lp",
        "vinyl-crowded-house-dont-dream-its-over-lp",
    ]
    assert messages == [
        "Indexing JB Hi-Fi vinyl: sitemap 1 of 2",
        "Indexing JB Hi-Fi vinyl: sitemap 2 of 2",
    ]


def test_slugs_follows_escaped_sitemap_addresses(cache: Cache) -> None:
    site = Site(SITEMAPS)
    catalogue_for(site, cache).slugs()
    assert [str(request.url) for request in site.requests] == [
        "http://shop.test/sitemap.xml",
        "http://shop.test/sitemap_products_1.xml?from=1&to=2",
        "http://shop.test/sitemap_products_2.xml?from=3&to=4",
    ]


def test_slugs_are_cached(cache: Cache) -> None:
    site = Site(SITEMAPS)
    first = catalogue_for(site, cache).slugs()
    downloads = len(site.requests)
    assert catalogue_for(site, cache).slugs() == first
    assert len(site.requests) == downloads


def test_slugs_fails_when_sitemap_is_unavailable(cache: Cache) -> None:
    with pytest.raises(JBHiFiError, match="could not download"):
        catalogue_for(Site({}), cache).slugs()


def test_slugs_fails_and_caches_nothing_without_vinyl(cache: Cache) -> None:
    site = Site({"/sitemap.xml": "<sitemapindex></sitemapindex>"})
    with pytest.raises(JBHiFiError, match="no vinyl"):
        catalogue_for(site, cache).slugs()
    assert catalogue_for(Site(SITEMAPS), cache).slugs()


def test_search_matches_every_word_newest_first(cache: Cache) -> None:
    catalogue = catalogue_for(Site(SITEMAPS), cache)
    assert catalogue.search("John Coltrane, Love Supreme", limit=10) == [
        "http://shop.test/products/vinyl-coltrane-john-a-love-supreme-reissue-lp",
        "http://shop.test/products/vinyl-coltrane-john-a-love-supreme-lp",
    ]


def test_search_respects_limit(cache: Cache) -> None:
    catalogue = catalogue_for(Site(SITEMAPS), cache)
    assert len(catalogue.search("coltrane", limit=1)) == 1


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("Beyoncé", "vinyl-beyonce-lemonade-2lp"),
        ("don't dream it's over", "vinyl-crowded-house-dont-dream-its-over-lp"),
    ],
)
def test_search_ignores_accents_and_apostrophes(
    cache: Cache, query: str, slug: str
) -> None:
    catalogue = catalogue_for(Site(SITEMAPS), cache)
    assert catalogue.search(query, limit=10) == [f"http://shop.test/products/{slug}"]


def test_search_with_no_words_or_no_match_is_empty(cache: Cache) -> None:
    catalogue = catalogue_for(Site(SITEMAPS), cache)
    assert catalogue.search("!!!", limit=10) == []
    assert catalogue.search("coltrane lemonade", limit=10) == []


def test_index_is_kept_per_storefront(cache: Cache) -> None:
    catalogue_for(Site(SITEMAPS), cache).slugs()
    elsewhere = httpx.Client(
        base_url="http://other.test", transport=httpx.MockTransport(Site({}))
    )
    with pytest.raises(JBHiFiError, match="could not download"):
        Catalogue(elsewhere, cache, sleep=lambda _: None).slugs()


def test_newest_lists_the_latest_additions_first(cache: Cache) -> None:
    catalogue = catalogue_for(Site(SITEMAPS), cache)
    assert catalogue.newest(limit=2) == [
        f"{SHOP}/products/vinyl-crowded-house-dont-dream-its-over-lp",
        f"{SHOP}/products/vinyl-coltrane-john-a-love-supreme-reissue-lp",
    ]


LISTING = f"""<main>
  <a href="/products/vinyl-misch-tom-full-circle-lp">Full Circle</a>
  <a href="/products/vinyl-misch-tom-full-circle-lp?variant=1">Full Circle</a>
  <a href='{SHOP}/products/vinyl-khalid-american-teen-2lp#reviews'>American Teen</a>
  <a href="/products/audio-technica-turntable">A turntable</a>
  <a href="/products/vinyl-peach-prc-porcelain-lp">Porcelain</a>
</main>"""


def test_listed_finds_the_vinyl_on_a_page_in_order(cache: Cache) -> None:
    pages = Pages(LISTING)
    catalogue = catalogue_for(Site({}), cache)
    listing = f"{SHOP}/collections/clearance"
    assert catalogue.listed(listing, pages, limit=10) == [
        f"{SHOP}/products/vinyl-misch-tom-full-circle-lp",
        f"{SHOP}/products/vinyl-khalid-american-teen-2lp",
        f"{SHOP}/products/vinyl-peach-prc-porcelain-lp",
    ]
    assert pages.loaded == [listing]
    assert pages.waited_for == ['a[href*="/products/vinyl-"]']


def test_listed_respects_limit(cache: Cache) -> None:
    catalogue = catalogue_for(Site({}), cache)
    listing = f"{SHOP}/collections/clearance"
    assert len(catalogue.listed(listing, Pages(LISTING), limit=2)) == 2
