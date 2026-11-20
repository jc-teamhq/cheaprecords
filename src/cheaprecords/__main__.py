"""Command-line entry point; also runnable with `python -m`."""

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager

import httpx

from cheaprecords import __version__
from cheaprecords.browser import ChromeFetcher
from cheaprecords.cache import Cache, default_cache_dir
from cheaprecords.compare import (
    NOTES,
    Comparison,
    best_first,
    render_json,
    render_table,
)
from cheaprecords.config import JBHIFI_DEALS_URL_VARIABLE, ConfigError, load_config
from cheaprecords.discogs import Discogs, DiscogsError
from cheaprecords.jbhifi import Catalogue, JBHiFiError, PageFetcher, load_record


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="cheaprecords",
        description=(
            "Compare JB Hi-Fi vinyl record prices against the Discogs marketplace."
        ),
        epilog=(
            "With no query, the newest additions to JB Hi-Fi's vinyl range are "
            "compared. The sites' addresses come from the environment: set "
            "CHEAPRECORDS_JBHIFI_URL and CHEAPRECORDS_DISCOGS_URL, and "
            "CHEAPRECORDS_JBHIFI_DEALS_URL to use --deals. Optionally set "
            "DISCOGS_TOKEN to a Discogs personal access token, which raises the "
            "Discogs rate limit from 25 to 60 requests a minute."
        ),
    )
    parser.add_argument(
        "query",
        nargs="*",
        help=(
            "words to find in JB Hi-Fi's vinyl range (e.g. coltrane love supreme), "
            "or the addresses of JB Hi-Fi product pages"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="most records to compare (default: %(default)s)",
    )
    parser.add_argument(
        "--deals",
        action="store_true",
        help=(
            "compare the records on JB Hi-Fi's deals page instead, to find where "
            "JB Hi-Fi's price is best against Discogs"
        ),
    )
    parser.add_argument(
        "--max-pressings",
        type=int,
        default=5,
        help="most Discogs pressings to price per record (default: %(default)s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print JSON instead of a table",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="ignore cached JB Hi-Fi and Discogs prices",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="rebuild the index of JB Hi-Fi's vinyl range",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _progress(message: str) -> None:
    print(message, file=sys.stderr)


def _searched(query: Sequence[str], catalogue: Catalogue, limit: int) -> list[str]:
    urls = [word for word in query if "://" in word]
    for url in urls:
        if not url.startswith(catalogue.product_url_prefix):
            message = f"not a JB Hi-Fi product page: {url}"
            raise JBHiFiError(message)
    words = [word for word in query if "://" not in word]
    if words:
        urls += catalogue.search(" ".join(words), limit)
    return list(dict.fromkeys(urls))


def _compare(
    urls: Sequence[str],
    pages: PageFetcher,
    discogs: Discogs,
    cache: Cache,
    max_pressings: int,
) -> list[Comparison]:
    comparisons = []
    for number, url in enumerate(urls, start=1):
        _progress(f"[{number}/{len(urls)}] {url.rsplit('/', 1)[-1]}")
        try:
            record = load_record(url, pages, cache)
        except JBHiFiError as exc:
            _progress(f"  skipped: {exc}")
            continue
        market = (
            discogs.market(record.barcode, max_pressings) if record.barcode else None
        )
        comparisons.append(Comparison(record, market))
    return comparisons


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    browser: Callable[[], AbstractContextManager[PageFetcher]] = ChromeFetcher,
) -> int:
    """Run the application.

    Args:
        argv: Command-line arguments, excluding the program name. Defaults to
            `sys.argv[1:]` when omitted; pass a list explicitly in tests.
        transport: Replaces the network for plain HTTP requests in tests.
        browser: Opens the browser JB Hi-Fi product pages are loaded in;
            replaced in tests.

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.deals and args.query:
        parser.error("--deals cannot be combined with a query")
    try:
        config = load_config()
    except ConfigError as exc:
        _progress(f"error: {exc}")
        return 1
    deals_url = config.jbhifi_deals_url if args.deals else None
    if args.deals and deals_url is None:
        _progress(
            f"error: {JBHIFI_DEALS_URL_VARIABLE} must be set to use --deals; "
            "see the README"
        )
        return 1
    cache_dir = default_cache_dir()
    prices = Cache(cache_dir, read=not args.refresh)
    headers = {"User-Agent": f"cheaprecords/{__version__}"}
    with (
        httpx.Client(
            base_url=config.jbhifi_url, headers=headers, timeout=30, transport=transport
        ) as jbhifi,
        httpx.Client(
            base_url=config.discogs_url,
            headers=headers,
            timeout=30,
            transport=transport,
        ) as discogs_api,
        browser() as pages,
    ):
        catalogue = Catalogue(
            jbhifi, Cache(cache_dir, read=not args.reindex), progress=_progress
        )
        discogs = Discogs(
            discogs_api, prices, token=config.discogs_token, progress=_progress
        )
        try:
            if deals_url is not None:
                _progress("Reading JB Hi-Fi's deals page")
                urls = catalogue.listed(deals_url, pages, args.limit)
            elif args.query:
                urls = _searched(args.query, catalogue, args.limit)
            else:
                urls = catalogue.newest(args.limit)
            comparisons = _compare(urls, pages, discogs, prices, args.max_pressings)
        except (JBHiFiError, DiscogsError) as exc:
            _progress(f"error: {exc}")
            return 1
    if not comparisons:
        _progress("No JB Hi-Fi vinyl found to compare.")
        return 1
    ordered = best_first(comparisons)
    if args.json:
        print(render_json(ordered))
    else:
        print(render_table(ordered))
        print()
        print(NOTES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
