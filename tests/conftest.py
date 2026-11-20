"""Shared fixtures and sample data."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from cheaprecords.cache import Cache


def _product_page(
    *,
    name: str = "A Love Supreme",
    price: str | None = "105.00",
    gtin: str | None = "11105015516",
    availability: str = "InStock",
) -> str:
    """Build a cut-down JB Hi-Fi product page."""
    offers = {"@type": "Offer", "availability": availability}
    if price is not None:
        offers["price"] = price
    product = {
        "@type": "Product",
        "name": name,
        "additionalProperty": [
            {"name": "Artist", "value": "JOHN COLTRANE"},
            {"name": "Label", "value": "Impulse Records"},
        ],
        "offers": offers,
    }
    if gtin is not None:
        product["gtin"] = gtin
    breadcrumbs = {"@type": "BreadcrumbList", "itemListElement": []}
    return (
        "<html><head>"
        '<script type="text/javascript">var notData = 1;</script>'
        '<script type="application/ld+json">{not json</script>'
        f'<script type="application/ld+json">{json.dumps(breadcrumbs)}</script>'
        f'<script type="application/ld+json">{json.dumps(product)}</script>'
        "</head><body><h1>A Love Supreme</h1></body></html>"
    )


@pytest.fixture
def product_page() -> Callable[..., str]:
    """The builder for sample product pages; see `_product_page` for options."""
    return _product_page


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache")
