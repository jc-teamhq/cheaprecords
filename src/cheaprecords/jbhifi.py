"""JB Hi-Fi: find vinyl in the public sitemap and read product pages."""

import json
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any, Protocol

import httpx

from cheaprecords.cache import Cache

INDEX_MAX_AGE = timedelta(days=7)
PRODUCT_MAX_AGE = timedelta(hours=6)
# Pause between sitemap downloads; there are over a hundred of them.
SITEMAP_DELAY = 0.5

_LOC = re.compile(r"<loc>([^<]+)</loc>")
# JB Hi-Fi prefixes the URL of every vinyl record with "vinyl-".
_VINYL_SLUG = re.compile(r"<loc>[^<]*/products/(vinyl-[^<]+)</loc>")
_VINYL_LINK = re.compile(r"""href=["'][^"']*/products/(vinyl-[^"'?#]+)""")
# Listing pages fill in their products after loading; this marks them as ready.
VINYL_LINK_SELECTOR = 'a[href*="/products/vinyl-"]'


class JBHiFiError(Exception):
    """JB Hi-Fi could not be read."""


class PageFetcher(Protocol):
    """Something that can load a JB Hi-Fi page and return its HTML."""

    def fetch(self, url: str, *, wait_for: str | None = None) -> str:
        """Return the HTML of the page at `url`, or raise `JBHiFiError`.

        Args:
            url: The address of the page to load.
            wait_for: A CSS selector that must match before the HTML is read,
                for pages that fill in their content after loading.
        """
        ...


@dataclass(frozen=True)
class Record:
    """A vinyl record as sold by JB Hi-Fi."""

    title: str
    artist: str
    price: float
    """Price in Australian dollars."""
    barcode: str | None
    url: str
    in_stock: bool


class _LinkedDataParser(HTMLParser):
    """Collects the contents of a page's JSON-LD script blocks."""

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and ("type", "application/ld+json") in attrs:
            self._inside = True
            self.blocks.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.blocks[-1] += data


def parse_product(page_html: str, url: str) -> Record:
    """Read a record's details from its JB Hi-Fi product page.

    Args:
        page_html: The HTML of the product page.
        url: The page's address, kept on the returned record.

    Returns:
        The record described by the page's structured product data.

    Raises:
        JBHiFiError: If the page has no usable product data.
    """
    parser = _LinkedDataParser()
    parser.feed(page_html)
    for block in parser.blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            return _record_from_linked_data(data, url)
    message = f"no product data found at {url}"
    raise JBHiFiError(message)


def _record_from_linked_data(data: dict[str, Any], url: str) -> Record:
    offers = data.get("offers") or {}
    try:
        price = float(offers["price"])
    except (KeyError, TypeError, ValueError) as exc:
        message = f"no price found at {url}"
        raise JBHiFiError(message) from exc
    properties = {
        item.get("name"): item.get("value")
        for item in data.get("additionalProperty") or []
    }
    barcode = data.get("gtin")
    return Record(
        title=str(data.get("name", "")),
        artist=str(properties.get("Artist", "")),
        price=price,
        barcode=str(barcode) if barcode else None,
        url=url,
        in_stock=str(offers.get("availability", "")).endswith("InStock"),
    )


def load_record(url: str, pages: PageFetcher, cache: Cache) -> Record:
    """Load a record from its product page, reusing a recent result if any.

    Args:
        url: The address of a JB Hi-Fi product page.
        pages: Loads the page when no recent result is cached.
        cache: Where results are kept between runs.

    Returns:
        The record sold at `url`.

    Raises:
        JBHiFiError: If the page cannot be loaded or has no product data.
    """
    cached = cache.get("jbhifi-product", url, PRODUCT_MAX_AGE)
    if cached is not None:
        return Record(**json.loads(cached))
    record = parse_product(pages.fetch(url), url)
    cache.put("jbhifi-product", url, json.dumps(asdict(record)))
    return record


def _tokens(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", plain.lower().replace("'", ""))


class Catalogue:
    """JB Hi-Fi's vinyl range, indexed from the site's public sitemap."""

    def __init__(
        self,
        client: httpx.Client,
        cache: Cache,
        *,
        progress: Callable[[str], None] = lambda _: None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a catalogue.

        Args:
            client: Used to download the sitemap; its `base_url` is the
                address of the JB Hi-Fi storefront.
            cache: Where the index is kept between runs.
            progress: Called with a status line while the index is built.
            sleep: Pauses between sitemap downloads; replaceable in tests.
        """
        self._client = client
        self._cache = cache
        self._progress = progress
        self._sleep = sleep
        self.product_url_prefix = str(client.base_url.join("/products/"))
        """What the address of every product page starts with."""

    def slugs(self) -> list[str]:
        """List the URL slug of every vinyl record, oldest product first.

        Returns:
            The slugs, from the cached index when it is recent enough and
            otherwise from a fresh read of the sitemap.

        Raises:
            JBHiFiError: If the sitemap cannot be read or lists no vinyl.
        """
        key = str(self._client.base_url)
        cached = self._cache.get("jbhifi-vinyl", key, INDEX_MAX_AGE)
        if cached is not None:
            return cached.split()
        sitemaps = [
            unescape(loc)
            for loc in _LOC.findall(self._get("/sitemap.xml"))
            if "sitemap_products_" in loc
        ]
        slugs: list[str] = []
        for number, sitemap in enumerate(sitemaps, start=1):
            self._progress(
                f"Indexing JB Hi-Fi vinyl: sitemap {number} of {len(sitemaps)}"
            )
            slugs.extend(_VINYL_SLUG.findall(self._get(sitemap)))
            self._sleep(SITEMAP_DELAY)
        if not slugs:
            message = "no vinyl found in the JB Hi-Fi sitemap"
            raise JBHiFiError(message)
        self._cache.put("jbhifi-vinyl", key, "\n".join(slugs))
        return slugs

    def search(self, query: str, limit: int) -> list[str]:
        """Find records whose URL contains every word of a query.

        Args:
            query: Words to look for, e.g. an artist and album title.
            limit: The most records to return.

        Returns:
            Product page addresses, newest product first.

        Raises:
            JBHiFiError: If the sitemap cannot be read.
        """
        wanted = set(_tokens(query))
        if not wanted:
            return []
        matches = [
            slug for slug in reversed(self.slugs()) if wanted <= set(slug.split("-"))
        ]
        return [self.product_url_prefix + slug for slug in matches[:limit]]

    def newest(self, limit: int) -> list[str]:
        """List the records most recently added to JB Hi-Fi's range.

        Args:
            limit: The most records to return.

        Returns:
            Product page addresses, newest product first.

        Raises:
            JBHiFiError: If the sitemap cannot be read.
        """
        newest_first = list(reversed(self.slugs()))
        return [self.product_url_prefix + slug for slug in newest_first[:limit]]

    def listed(self, url: str, pages: PageFetcher, limit: int) -> list[str]:
        """List the records shown on a JB Hi-Fi listing page, such as a sale.

        Only the records the page shows when first opened are found; any
        behind its "load more" button are not.

        Args:
            url: The address of the listing page.
            pages: Loads the page.
            limit: The most records to return.

        Returns:
            Product page addresses, in the order the page shows them.

        Raises:
            JBHiFiError: If the page cannot be loaded or shows no vinyl.
        """
        page_html = pages.fetch(url, wait_for=VINYL_LINK_SELECTOR)
        slugs = list(dict.fromkeys(_VINYL_LINK.findall(page_html)))
        return [self.product_url_prefix + slug for slug in slugs[:limit]]

    def _get(self, url: str) -> str:
        try:
            response = self._client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            message = f"could not download {url}: {exc}"
            raise JBHiFiError(message) from exc
        return response.text
