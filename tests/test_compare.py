"""Tests for comparing and rendering prices."""

import json

import pytest

from cheaprecords.compare import Comparison, best_first, render_json, render_table
from cheaprecords.discogs import Market
from cheaprecords.jbhifi import Record


def record(title: str = "A Love Supreme", price: float = 105.0) -> Record:
    return Record(
        title=title,
        artist="JOHN COLTRANE",
        price=price,
        barcode="11105015516",
        url="http://shop.test/products/vinyl-x",
        in_stock=True,
    )


def market(lowest: float | None = 29.41) -> Market:
    for_sale = 0 if lowest is None else 69
    return Market(
        pressings=19,
        checked=5,
        for_sale=for_sale,
        lowest=lowest,
        median=lowest,
        rating=None if lowest is None else 4.67,
        votes=0 if lowest is None else 593,
    )


def test_difference_is_jb_minus_discogs_low() -> None:
    assert Comparison(record(), market()).difference == pytest.approx(75.59)


def test_no_difference_without_a_discogs_price() -> None:
    assert Comparison(record(), None).difference is None
    assert Comparison(record(), market(lowest=None)).difference is None


def test_best_first_puts_jb_bargains_first_and_unpriced_last() -> None:
    dearer = Comparison(record("Dearer", 105.0), market(29.41))
    unmatched = Comparison(record("Unmatched"), None)
    cheaper = Comparison(record("Cheaper", 20.0), market(29.41))
    ordered = best_first([dearer, unmatched, cheaper])
    assert [item.record.title for item in ordered] == [
        "Cheaper",
        "Dearer",
        "Unmatched",
    ]


def test_render_table() -> None:
    table = render_table(
        [
            Comparison(record(), market()),
            Comparison(record("Nothing For Sale", 50.0), market(lowest=None)),
            Comparison(record("Unknown To Discogs", 40.0), None),
        ]
    )
    assert table.splitlines() == [
        "Record                              In stock  JB Hi-Fi  Discogs low  Median"
        "  For sale  Pressings      Rating  Difference",
        "JOHN COLTRANE - A Love Supreme           yes    105.00        29.41   29.41"
        "        69    5 of 19  4.67 (593)      +75.59",
        "JOHN COLTRANE - Nothing For Sale         yes     50.00            -       -"
        "         0    5 of 19           -           -",
        "JOHN COLTRANE - Unknown To Discogs       yes     40.00     no match       -"
        "         -          -           -           -",
    ]


def test_render_table_shortens_long_names_and_flags_stock() -> None:
    long_title = "A Love Supreme (180gm Vinyl) (Reissue) (Limited Edition)"
    sold_out = Record(
        title=long_title, artist="", price=1.0, barcode=None, url="u", in_stock=False
    )
    row = render_table([Comparison(sold_out, None)]).splitlines()[1]
    assert row.startswith("A Love Supreme (180gm Vinyl) (Reissue) (Limited…")
    assert row.split()[-9:-7] == ["no", "1.00"]


def test_render_json() -> None:
    rendered = render_json([Comparison(record(), market()), Comparison(record(), None)])
    first, second = json.loads(rendered)
    assert first["record"]["title"] == "A Love Supreme"
    assert first["discogs"] == {
        "pressings": 19,
        "checked": 5,
        "for_sale": 69,
        "lowest": 29.41,
        "median": 29.41,
        "rating": 4.67,
        "votes": 593,
    }
    assert first["difference"] == 75.59
    assert second["discogs"] is None
    assert second["difference"] is None
