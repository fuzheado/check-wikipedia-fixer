"""
SQLite-based progress cache for tracking article fixes across sessions.

Stores which articles have been processed, how many <b> tags were fixed,
and whether the article was skipped. Supports resume from last position.
"""

import sqlite3
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class CacheError(Exception):
    """Raised when cache operations fail."""
    pass


@dataclass
class CachedArticle:
    """An article record from the cache."""
    title: str
    url: str
    status: str = 'pending'     # pending, fixed, skipped
    fix_count: int = 0
    sort_order: int = 0         # matches DB column name
    updated_at: Optional[str] = None


class ProgressCache:
    """
    SQLite-backed progress tracker.

    Thread-safe for single-writer access. Stores article state so the
    user can quit and resume from where they left off.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._open()

    def _open(self):
        """Open the database connection and create tables if needed."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                title TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                fix_count INTEGER NOT NULL DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        self._conn.commit()

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def add_article(self, title: str, url: str, order: int = 0):
        """
        Add an article to the cache if it doesn't exist.
        If it already exists, update only if still pending.
        """
        self._conn.execute("""
            INSERT OR IGNORE INTO articles (title, url, status, sort_order)
            VALUES (?, ?, 'pending', ?)
        """, (title, url, order))
        self._conn.commit()

    def add_articles(self, articles: list):
        """Add multiple articles at once."""
        for i, (title, url) in enumerate(articles):
            self.add_article(title, url, order=i)
        self._conn.commit()

    def mark_fixed(self, title: str, fixes: int = 0):
        """Mark an article as fixed."""
        self._conn.execute("""
            UPDATE articles
            SET status = 'fixed', fix_count = ?, updated_at = ?
            WHERE title = ?
        """, (fixes, datetime.now(timezone.utc).isoformat(), title))
        self._conn.commit()

    def mark_skipped(self, title: str):
        """Mark an article as skipped (user chose not to fix)."""
        self._conn.execute("""
            UPDATE articles
            SET status = 'skipped', updated_at = ?
            WHERE title = ?
        """, (datetime.now(timezone.utc).isoformat(), title))
        self._conn.commit()

    def get_status(self, title: str) -> Optional[str]:
        """Get the status of an article."""
        row = self._conn.execute(
            "SELECT status FROM articles WHERE title = ?", (title,)
        ).fetchone()
        return row['status'] if row else None

    def get_fix_count(self, title: str) -> int:
        """Get the fix count for an article."""
        row = self._conn.execute(
            "SELECT fix_count FROM articles WHERE title = ?", (title,)
        ).fetchone()
        return row['fix_count'] if row else 0

    def get_pending(self) -> list:
        """Get all pending articles, ordered by sort_order."""
        rows = self._conn.execute("""
            SELECT title, url, status, fix_count, sort_order, updated_at
            FROM articles
            WHERE status = 'pending'
            ORDER BY sort_order ASC
        """).fetchall()
        return [CachedArticle(**dict(r)) for r in rows]

    def count_all(self) -> int:
        """Total number of articles in the cache."""
        row = self._conn.execute("SELECT COUNT(*) FROM articles").fetchone()
        return row[0]

    def count_pending(self) -> int:
        """Number of pending articles."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM articles WHERE status = 'pending'"
        ).fetchone()
        return row[0]

    def count_fixed(self) -> int:
        """Number of fixed articles."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM articles WHERE status = 'fixed'"
        ).fetchone()
        return row[0]

    def count_skipped(self) -> int:
        """Number of skipped articles."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM articles WHERE status = 'skipped'"
        ).fetchone()
        return row[0]

    def total_fixes(self) -> int:
        """Total number of <b> tags fixed across all articles."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(fix_count), 0) FROM articles WHERE status = 'fixed'"
        ).fetchone()
        return row[0]

    def get_stats(self) -> dict:
        """Get a summary of cache statistics."""
        return {
            'total': self.count_all(),
            'pending': self.count_pending(),
            'fixed': self.count_fixed(),
            'skipped': self.count_skipped(),
            'total_fixes': self.total_fixes(),
        }

    def reset(self):
        """Clear all cached data."""
        self._conn.execute("DELETE FROM articles")
        self._conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
