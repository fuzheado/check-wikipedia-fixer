"""Tests for the progress cache."""

import pytest
import tempfile
from pathlib import Path

from cwfix.cache import ProgressCache, CacheError


class TestProgressCache:
    """Tests for the SQLite-based progress cache."""

    @pytest.fixture
    def cache(self):
        """Create a temporary cache for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_cache.db"
            cache = ProgressCache(db_path)
            yield cache
            cache.close()

    def test_new_cache_is_empty(self, cache):
        """Fresh cache has no articles."""
        assert cache.count_all() == 0
        assert cache.count_pending() == 0

    def test_add_article(self, cache):
        """Adding an article creates a record."""
        cache.add_article("Test Article", "http://example.com/wiki/Test_Article")
        assert cache.count_all() == 1
        assert cache.count_pending() == 1

    def test_add_article_deduplicates(self, cache):
        """Adding the same article twice is idempotent."""
        cache.add_article("Test Article", "http://example.com/wiki/Test_Article")
        cache.add_article("Test Article", "http://example.com/wiki/Test_Article")
        assert cache.count_all() == 1

    def test_add_multiple_articles(self, cache):
        """Multiple articles can be added."""
        cache.add_article("Article A", "http://example.com/A")
        cache.add_article("Article B", "http://example.com/B")
        cache.add_article("Article C", "http://example.com/C")
        assert cache.count_all() == 3
        assert cache.count_pending() == 3

    def test_mark_fixed(self, cache):
        """Marking an article as fixed updates status."""
        cache.add_article("Test Article", "http://example.com/wiki/Test_Article")
        cache.mark_fixed("Test Article", fixes=5)
        assert cache.count_pending() == 0
        assert cache.count_all() == 1
        status = cache.get_status("Test Article")
        assert status == 'fixed'

    def test_mark_skipped(self, cache):
        """Marking an article as skipped."""
        cache.add_article("Test Article", "http://example.com/wiki/Test_Article")
        cache.mark_skipped("Test Article")
        assert cache.count_pending() == 0
        assert cache.get_status("Test Article") == 'skipped'

    def test_mark_unknown_article(self, cache):
        """Marking an unknown article is a no-op (or logs)."""
        # Should not raise
        cache.mark_fixed("Nonexistent", fixes=0)

    def test_get_pending_articles(self, cache):
        """Pending articles can be retrieved in order."""
        cache.add_article("Article B", "http://example.com/B")
        cache.add_article("Article A", "http://example.com/A")
        cache.add_article("Article C", "http://example.com/C")
        pending = cache.get_pending()
        assert len(pending) == 3

    def test_get_pending_excludes_fixed(self, cache):
        """Fixed articles are not in pending list."""
        cache.add_article("Article A", "http://example.com/A")
        cache.add_article("Article B", "http://example.com/B")
        cache.mark_fixed("Article A")
        pending = cache.get_pending()
        assert len(pending) == 1
        assert pending[0].title == "Article B"

    def test_get_pending_excludes_skipped(self, cache):
        """Skipped articles are not in pending list."""
        cache.add_article("Article A", "http://example.com/A")
        cache.add_article("Article B", "http://example.com/B")
        cache.mark_skipped("Article A")
        pending = cache.get_pending()
        assert len(pending) == 1
        assert pending[0].title == "Article B"

    def test_get_pending_respects_order(self, cache):
        """Pending articles return in added order."""
        cache.add_article("C", "http://example.com/C", order=2)
        cache.add_article("A", "http://example.com/A", order=0)
        cache.add_article("B", "http://example.com/B", order=1)
        pending = cache.get_pending()
        assert [a.title for a in pending] == ["A", "B", "C"]

    def test_get_status_unknown(self, cache):
        """Unknown article returns None."""
        assert cache.get_status("Nonexistent") is None

    def test_get_fix_count(self, cache):
        """Fix count is tracked."""
        cache.add_article("Test Article", "http://example.com/wiki/Test_Article")
        cache.mark_fixed("Test Article", fixes=22)
        assert cache.get_fix_count("Test Article") == 22

    def test_get_fix_count_default(self, cache):
        """Unfixed article has fix count of 0."""
        cache.add_article("Test Article", "http://example.com/wiki/Test_Article")
        assert cache.get_fix_count("Test Article") == 0

    def test_cache_persistence(self, cache):
        """Cache persists data within same instance."""
        cache.add_article("Persist Me", "http://example.com/Persist_Me")
        cache.mark_fixed("Persist Me", fixes=3)
        assert cache.get_fix_count("Persist Me") == 3
        assert cache.get_status("Persist Me") == 'fixed'

    def test_reset(self, cache):
        """Resetting clears all data."""
        cache.add_article("Article A", "http://example.com/A")
        cache.add_article("Article B", "http://example.com/B")
        cache.reset()
        assert cache.count_all() == 0

    def test_stats(self, cache):
        """Stats returns summary dict."""
        cache.add_article("A", "http://example.com/A")
        cache.add_article("B", "http://example.com/B")
        cache.add_article("C", "http://example.com/C")
        cache.mark_fixed("A", fixes=5)
        cache.mark_skipped("B")
        stats = cache.get_stats()
        assert stats['total'] == 3
        assert stats['fixed'] == 1
        assert stats['skipped'] == 1
        assert stats['pending'] == 1
        assert stats['total_fixes'] == 5


class TestCacheError:
    """Tests for the cache exception."""

    def test_cache_error(self):
        """CacheError has a message."""
        error = CacheError("Database error")
        assert str(error) == "Database error"
        assert isinstance(error, Exception)
