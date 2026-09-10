"""
Incremental crawl state management using SQLite.

Tracks:
- Which URLs have been crawled
- When they were crawled
- Content timestamps (post creation time)
- Last run times per platform

Enables:
- Incremental crawls (only fetch new URLs)
- Deduplication across keywords
- Content-timestamp freshness decisions (see crawl_freshness.py)

Note: Search rankings are NOT chronological. Do not stop scrolling solely
because previously seen URLs appeared consecutively.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class IncrementalCrawlState:
    """Manages state for incremental social media crawling"""

    def __init__(self, db_path: str | Path = "data/crawl_state.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._setup_tables()

    def _setup_tables(self) -> None:
        """Create database schema if not exists"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS crawled_urls (
                url TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                keyword TEXT,
                first_crawled_at TIMESTAMP NOT NULL,
                last_seen_at TIMESTAMP NOT NULL,
                content_timestamp TIMESTAMP,
                crawl_count INTEGER DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_crawled_urls_platform
                ON crawled_urls(platform);

            CREATE INDEX IF NOT EXISTS idx_crawled_urls_content_timestamp
                ON crawled_urls(content_timestamp);

            CREATE TABLE IF NOT EXISTS crawl_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                run_type TEXT NOT NULL,  -- 'initial' or 'incremental'
                started_at TIMESTAMP NOT NULL,
                completed_at TIMESTAMP,
                urls_discovered INTEGER DEFAULT 0,
                urls_crawled INTEGER DEFAULT 0,
                urls_skipped INTEGER DEFAULT 0,
                duration_seconds INTEGER,
                keywords_processed INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_crawl_runs_platform
                ON crawl_runs(platform, started_at DESC);
        """)
        self.conn.commit()

    def get_existing_urls(self, platform: str, since: Optional[datetime] = None) -> set[str]:
        """Get set of URLs already crawled for a platform"""
        query = "SELECT url FROM crawled_urls WHERE platform = ?"
        params = [platform]

        if since:
            query += " AND first_crawled_at >= ?"
            params.append(since.isoformat())

        cursor = self.conn.execute(query, params)
        return {row[0] for row in cursor.fetchall()}

    def is_url_crawled(self, url: str) -> bool:
        """Check if URL has been crawled before"""
        cursor = self.conn.execute(
            "SELECT 1 FROM crawled_urls WHERE url = ? LIMIT 1",
            (url,)
        )
        return cursor.fetchone() is not None

    def mark_crawled(
        self,
        url: str,
        platform: str,
        keyword: str = "",
        content_timestamp: Optional[str | datetime] = None
    ) -> None:
        """Mark a URL as crawled"""
        now = datetime.now()

        # Normalize content_timestamp
        if isinstance(content_timestamp, str):
            try:
                content_timestamp = datetime.fromisoformat(content_timestamp.replace("Z", "+00:00"))
            except ValueError:
                content_timestamp = None

        content_ts = content_timestamp.isoformat() if content_timestamp else None

        self.conn.execute("""
            INSERT INTO crawled_urls
            (url, platform, keyword, first_crawled_at, last_seen_at, content_timestamp, crawl_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(url) DO UPDATE SET
                last_seen_at = ?,
                crawl_count = crawl_count + 1,
                content_timestamp = COALESCE(?, content_timestamp)
        """, (url, platform, keyword, now, now, content_ts, now, content_ts))
        self.conn.commit()

    def should_stop_search(
        self,
        platform: str,
        recent_urls: list[str],
        threshold: int = 8,
        window: int = 10
    ) -> bool:
        """
        DEPRECATED / unsafe for non-chronological search.

        Previously stopped when recent_urls were already in crawl_state. Search
        rankings are not chronological, so consecutive previously-seen URLs do
        NOT imply a freshness boundary. Always returns False.

        Use crawl_freshness.should_stop_for_validated_stale_content() with real
        content timestamps instead.
        """
        return False

    def get_urls_with_content_timestamp(
        self,
        platform: str,
        *,
        since: Optional[datetime] = None,
    ) -> dict[str, Optional[datetime]]:
        """Return url -> content_timestamp for a platform (None if unknown)."""
        query = """
            SELECT url, content_timestamp
            FROM crawled_urls
            WHERE platform = ?
        """
        params: list = [platform]
        if since:
            query += " AND first_crawled_at >= ?"
            params.append(since.isoformat())
        cursor = self.conn.execute(query, params)
        out: dict[str, Optional[datetime]] = {}
        for row in cursor.fetchall():
            ts = row[1]
            if ts:
                try:
                    out[row[0]] = datetime.fromisoformat(ts)
                except ValueError:
                    out[row[0]] = None
            else:
                out[row[0]] = None
        return out

    def get_known_urls(self, *platforms: str) -> set[str]:
        """Union of crawled URLs across one or more platform keys."""
        known: set[str] = set()
        for platform in platforms:
            if platform:
                known |= self.get_existing_urls(platform)
        return known

    def get_last_run_time(self, platform: str) -> Optional[datetime]:
        """Get timestamp of last successful run for platform"""
        cursor = self.conn.execute("""
            SELECT completed_at
            FROM crawl_runs
            WHERE platform = ? AND completed_at IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 1
        """, (platform,))

        row = cursor.fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None

    def is_initial_run(self, platform: str) -> bool:
        """Check if this is the first run for a platform"""
        existing_urls = self.get_existing_urls(platform)
        return len(existing_urls) == 0

    def start_run(
        self,
        platform: str,
        run_type: str = "incremental"
    ) -> int:
        """Start a new crawl run, returns run_id"""
        cursor = self.conn.execute("""
            INSERT INTO crawl_runs (platform, run_type, started_at)
            VALUES (?, ?, ?)
        """, (platform, run_type, datetime.now()))
        self.conn.commit()
        return cursor.lastrowid

    def complete_run(
        self,
        run_id: int,
        urls_discovered: int = 0,
        urls_crawled: int = 0,
        urls_skipped: int = 0,
        keywords_processed: int = 0
    ) -> None:
        """Mark a crawl run as completed"""
        now = datetime.now()

        # Get start time to calculate duration
        cursor = self.conn.execute(
            "SELECT started_at FROM crawl_runs WHERE run_id = ?",
            (run_id,)
        )
        row = cursor.fetchone()

        duration = None
        if row:
            started_at = datetime.fromisoformat(row[0])
            duration = int((now - started_at).total_seconds())

        self.conn.execute("""
            UPDATE crawl_runs
            SET completed_at = ?,
                urls_discovered = ?,
                urls_crawled = ?,
                urls_skipped = ?,
                keywords_processed = ?,
                duration_seconds = ?
            WHERE run_id = ?
        """, (now, urls_discovered, urls_crawled, urls_skipped, keywords_processed, duration, run_id))
        self.conn.commit()

    def get_run_stats(self, platform: str, limit: int = 5) -> list[dict]:
        """Get recent run statistics for a platform"""
        cursor = self.conn.execute("""
            SELECT
                run_id,
                run_type,
                started_at,
                completed_at,
                urls_discovered,
                urls_crawled,
                urls_skipped,
                duration_seconds,
                keywords_processed
            FROM crawl_runs
            WHERE platform = ?
            ORDER BY started_at DESC
            LIMIT ?
        """, (platform, limit))

        return [dict(row) for row in cursor.fetchall()]

    def get_url_count(self, platform: str) -> int:
        """Get total URLs crawled for platform"""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM crawled_urls WHERE platform = ?",
            (platform,)
        )
        return cursor.fetchone()[0]

    def get_stats_summary(self, platform: str) -> dict:
        """Get summary statistics for a platform"""
        cursor = self.conn.execute("""
            SELECT
                COUNT(*) as total_urls,
                COUNT(DISTINCT keyword) as unique_keywords,
                MIN(first_crawled_at) as first_crawl,
                MAX(last_seen_at) as last_crawl,
                COUNT(CASE WHEN content_timestamp IS NOT NULL THEN 1 END) as urls_with_timestamp
            FROM crawled_urls
            WHERE platform = ?
        """, (platform,))

        row = cursor.fetchone()
        return dict(row) if row else {}

    def close(self) -> None:
        """Close database connection"""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
