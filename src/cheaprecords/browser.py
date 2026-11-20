"""Loads JB Hi-Fi pages in a real, headless Google Chrome.

JB Hi-Fi's storefront turns away plain HTTP clients, so product pages are
read the way a visitor's browser reads them: one at a time, with a pause
between pages, and without downloading images, fonts or video.

This module needs Chrome and the network, so it is left out of the test
suite and of coverage (see `[tool.coverage.run]` in pyproject.toml).
"""

import time
from typing import Self

from playwright.sync_api import Browser, Page, Playwright, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from cheaprecords.jbhifi import JBHiFiError

_OK = 200
_SKIPPED_RESOURCES = frozenset({"image", "media", "font"})
_TIMEOUT_MS = 45_000
# Once the first awaited element appears, give the rest of the list time to.
_SETTLE_MS = 1_500


def _skip_heavy_resources(route: Route) -> None:
    if route.request.resource_type in _SKIPPED_RESOURCES:
        route.abort()
    else:
        route.continue_()


class ChromeFetcher:
    """A `PageFetcher` backed by headless Chrome, started on first use."""

    def __init__(self, *, delay: float = 2.0) -> None:
        """Create a fetcher.

        Args:
            delay: Minimum number of seconds between page loads.
        """
        self._delay = delay
        self._ready_at = 0.0
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    def __enter__(self) -> Self:
        """Return the fetcher; Chrome itself starts on the first fetch."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close Chrome if it was started."""
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def fetch(self, url: str, *, wait_for: str | None = None) -> str:
        """Load a page and return its HTML.

        Args:
            url: The address of the page to load.
            wait_for: A CSS selector that must match before the HTML is read,
                for pages that fill in their content after loading.

        Returns:
            The page's HTML once its document has loaded and, if `wait_for`
            is given, the page has settled with a match for it.

        Raises:
            JBHiFiError: If Chrome cannot start or the page does not load.
        """
        page = self._open()
        time.sleep(max(0.0, self._ready_at - time.monotonic()))
        try:
            response = page.goto(url, wait_until="domcontentloaded")
            status = response.status if response else None
            if wait_for is not None and status == _OK:
                page.wait_for_selector(wait_for, state="attached")
                page.wait_for_timeout(_SETTLE_MS)
            page_html = page.content()
        except PlaywrightError as exc:
            message = f"could not load {url}: {exc.message}"
            raise JBHiFiError(message) from exc
        finally:
            self._ready_at = time.monotonic() + self._delay
        if status != _OK:
            message = f"{url} returned HTTP {status}"
            raise JBHiFiError(message)
        return page_html

    def _open(self) -> Page:
        if self._page is None:
            try:
                self._playwright = sync_playwright().start()
                self._browser = self._playwright.chromium.launch(
                    channel="chrome", headless=True
                )
                self._page = self._browser.new_page()
                self._page.set_default_timeout(_TIMEOUT_MS)
                self._page.route("**/*", _skip_heavy_resources)
            except PlaywrightError as exc:
                message = f"could not start Google Chrome: {exc.message}"
                raise JBHiFiError(message) from exc
        return self._page
