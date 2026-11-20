"""Tests for the on-disk cache."""

import os
import time
from datetime import timedelta
from pathlib import Path

import pytest

from cheaprecords.cache import Cache, default_cache_dir

HOUR = timedelta(hours=1)


def test_returns_what_was_stored(cache: Cache) -> None:
    cache.put("prices", "abc", "12.50")
    assert cache.get("prices", "abc", HOUR) == "12.50"


def test_missing_entry_is_none(cache: Cache) -> None:
    assert cache.get("prices", "abc", HOUR) is None


def test_namespaces_are_separate(cache: Cache) -> None:
    cache.put("prices", "abc", "12.50")
    assert cache.get("other", "abc", HOUR) is None


def test_old_entry_is_ignored(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    cache.put("prices", "abc", "12.50")
    two_hours_ago = time.time() - 2 * 60 * 60
    for path in tmp_path.rglob("*.txt"):
        os.utime(path, (two_hours_ago, two_hours_ago))
    assert cache.get("prices", "abc", HOUR) is None
    assert cache.get("prices", "abc", timedelta(hours=3)) == "12.50"


def test_read_false_ignores_but_still_stores(tmp_path: Path) -> None:
    Cache(tmp_path).put("prices", "abc", "old")
    refreshing = Cache(tmp_path, read=False)
    assert refreshing.get("prices", "abc", HOUR) is None
    refreshing.put("prices", "abc", "new")
    assert Cache(tmp_path).get("prices", "abc", HOUR) == "new"


def test_default_dir_honours_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "/somewhere/cache")
    assert default_cache_dir() == Path("/somewhere/cache/cheaprecords")


def test_default_dir_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert default_cache_dir() == Path.home() / ".cache" / "cheaprecords"
