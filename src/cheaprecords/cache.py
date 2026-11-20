"""A small on-disk text cache whose entries expire by age."""

import hashlib
import os
import time
from datetime import timedelta
from pathlib import Path


def default_cache_dir() -> Path:
    """Return the directory cached lookups are kept in.

    Returns:
        `$XDG_CACHE_HOME/cheaprecords`, or `~/.cache/cheaprecords` when the
        variable is unset.
    """
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "cheaprecords"


class Cache:
    """Text values stored one file per key, grouped by namespace."""

    def __init__(self, directory: Path, *, read: bool = True) -> None:
        """Create a cache.

        Args:
            directory: Where entries are stored; created on first write.
            read: Pass False to ignore stored entries (they are still
                overwritten), which forces every lookup to be fetched afresh.
        """
        self._directory = directory
        self._read = read

    def get(self, namespace: str, key: str, max_age: timedelta) -> str | None:
        """Look up a stored value.

        Args:
            namespace: The group the entry belongs to.
            key: The entry's key within the namespace.
            max_age: Entries stored longer ago than this are ignored.

        Returns:
            The stored text, or None if it is missing or too old.
        """
        if not self._read:
            return None
        path = self._path(namespace, key)
        try:
            age = time.time() - path.stat().st_mtime
        except FileNotFoundError:
            return None
        if age > max_age.total_seconds():
            return None
        return path.read_text(encoding="utf-8")

    def put(self, namespace: str, key: str, text: str) -> None:
        """Store a value, replacing any earlier one.

        Args:
            namespace: The group the entry belongs to.
            key: The entry's key within the namespace.
            text: The value to store.
        """
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _path(self, namespace: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self._directory / namespace / f"{digest}.txt"
