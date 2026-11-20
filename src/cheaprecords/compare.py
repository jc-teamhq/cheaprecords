"""Set JB Hi-Fi prices against Discogs prices and render the result."""

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from cheaprecords.discogs import Market
from cheaprecords.jbhifi import Record

NOTES = (
    "Discogs prices are the lowest asking price in AUD, in any condition, "
    "before postage.\n"
    "Rating is the Discogs community's average out of 5 for the most collected "
    "pressing, with the number of votes.\n"
    "Difference is JB Hi-Fi minus Discogs low; negative means JB Hi-Fi is cheaper."
)

_HEADINGS = (
    "Record",
    "In stock",
    "JB Hi-Fi",
    "Discogs low",
    "Median",
    "For sale",
    "Pressings",
    "Rating",
    "Difference",
)
_NAME_WIDTH = 48


@dataclass(frozen=True)
class Comparison:
    """A JB Hi-Fi record alongside its Discogs marketplace prices."""

    record: Record
    market: Market | None
    """None when Discogs has no vinyl release with the record's barcode."""

    @property
    def difference(self) -> float | None:
        """JB Hi-Fi's price minus the cheapest Discogs listing, if there is one."""
        if self.market is None or self.market.lowest is None:
            return None
        return self.record.price - self.market.lowest


def best_first(comparisons: Iterable[Comparison]) -> list[Comparison]:
    """Order comparisons with JB Hi-Fi's best prices first.

    Args:
        comparisons: The comparisons to order.

    Returns:
        The comparisons by ascending difference; those with no Discogs price
        to compare against come last.
    """
    return sorted(
        comparisons,
        key=lambda item: (item.difference is None, item.difference or 0.0),
    )


def _money(amount: float | None, *, signed: bool = False) -> str:
    if amount is None:
        return "-"
    return f"{amount:+.2f}" if signed else f"{amount:.2f}"


def _row(comparison: Comparison) -> tuple[str, ...]:
    record, market = comparison.record, comparison.market
    name = f"{record.artist} - {record.title}" if record.artist else record.title
    if len(name) > _NAME_WIDTH:
        name = name[: _NAME_WIDTH - 1] + "…"
    cells = (name, "yes" if record.in_stock else "no", _money(record.price))
    if market is None:
        return (*cells, "no match", "-", "-", "-", "-", "-")
    return (
        *cells,
        _money(market.lowest),
        _money(market.median),
        str(market.for_sale),
        f"{market.checked} of {market.pressings}",
        "-" if market.rating is None else f"{market.rating:.2f} ({market.votes})",
        _money(comparison.difference, signed=True),
    )


def render_table(comparisons: Iterable[Comparison]) -> str:
    """Render comparisons as a plain-text table.

    Args:
        comparisons: The comparisons to show, in display order.

    Returns:
        The table, one comparison per line under a heading row.
    """
    rows = [_HEADINGS, *(_row(comparison) for comparison in comparisons)]
    widths = [max(len(cell) for cell in column) for column in zip(*rows, strict=True)]
    lines = []
    for row in rows:
        name, *numbers = (
            cell.ljust(width) if index == 0 else cell.rjust(width)
            for index, (cell, width) in enumerate(zip(row, widths, strict=True))
        )
        lines.append("  ".join([name, *numbers]).rstrip())
    return "\n".join(lines)


def render_json(comparisons: Iterable[Comparison]) -> str:
    """Render comparisons as a JSON array.

    Args:
        comparisons: The comparisons to show, in display order.

    Returns:
        Indented JSON with each record, its Discogs prices (null when there
        is no match) and the difference.
    """
    return json.dumps(
        [
            {
                "record": asdict(comparison.record),
                "discogs": asdict(comparison.market) if comparison.market else None,
                "difference": (
                    None
                    if comparison.difference is None
                    else round(comparison.difference, 2)
                ),
            }
            for comparison in comparisons
        ],
        indent=2,
    )
