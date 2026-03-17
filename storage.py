#!/usr/bin/env python3
"""
Historical token usage storage — SQLite backend.
Stores periodic snapshots of token usage for later analysis and graphing.
"""

import sqlite3
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
from threading import Lock
from config import get_config

# ── Config ────────────────────────────────────────────────────────────────────
_config = get_config()

DB_PATH = Path.home() / ".cache" / "token-tracker" / "usage.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Sampling thresholds
MIN_TOKENS_FOR_SNAPSHOT = _config.MIN_TOKENS_FOR_SNAPSHOT
MAX_SNAPSHOTS_PER_DAY = 1440            # 1 per minute max (24h * 60)
RETENTION_DAYS = _config.RETENTION_DAYS

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,               -- Unix epoch seconds
    project_slug TEXT NOT NULL,            -- derived from cwd or folder name
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,         -- computed: input + output
    context_pct REAL NOT NULL,             -- input / CONTEXT_LIMIT * 100
    source_file TEXT NOT NULL,             -- session file path
    cwd TEXT NOT NULL                      -- working directory at time
);

CREATE INDEX IF NOT EXISTS idx_timestamp ON snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_project ON snapshots(project_slug);
"""


class StorageError(Exception):
    """Custom exception for storage failures."""
    pass


class SQLiteStorage:
    """
    Thread-safe SQLite storage for token usage history.

    Usage:
        storage = SQLiteStorage()
        storage.record_snapshot(sessions)  # sessions from get_sessions()
        history = storage.get_usage_history(days=7)
        project_totals = storage.get_project_totals(days=30)
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self._lock = Lock()
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def record_snapshot(self, sessions: List[Dict[str, Any]]) -> bool:
        """
        Record a snapshot of current sessions.

        Sampling strategy:
        - Only record if the primary session has >= MIN_TOKENS_FOR_SNAPSHOT
        - Throttle to max MAX_SNAPSHOTS_PER_DAY to prevent bloat
        - Always record if it's been >15 minutes since last snapshot for this project

        Returns: True if a snapshot was recorded, False otherwise.
        """
        if not sessions:
            return False

        # Focus on the primary (hottest) session
        primary = max(sessions, key=lambda s: s["pct"])
        inp = primary["input_tokens"]
        out = primary["output_tokens"]
        total = inp + out

        # Skip if usage is too small
        if total < MIN_TOKENS_FOR_SNAPSHOT:
            return False

        # Throttle: check recent snapshots for this project
        project_slug = self._slugify(primary.get("label", "unknown"))
        now = time.time()
        cutoff_24h = now - (24 * 3600)

        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Count snapshots in last 24h for this project
            cursor.execute("""
                SELECT COUNT(*) FROM snapshots
                WHERE project_slug = ? AND timestamp > ?
            """, (project_slug, cutoff_24h))
            count = cursor.fetchone()[0]

            if count >= MAX_SNAPSHOTS_PER_DAY:
                return False

            # Check last snapshot time for this project
            cursor.execute("""
                SELECT timestamp FROM snapshots
                WHERE project_slug = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (project_slug,))
            row = cursor.fetchone()
            if row and (now - row[0]) < 900:  # < 15 minutes
                return False

            # Insert the snapshot
            context_pct = primary.get("pct", 0.0)
            cwd = primary.get("cwd", "")
            source_file = cwd  # We don't have the exact file path in aggregated session

            try:
                cursor.execute("""
                    INSERT INTO snapshots
                    (timestamp, project_slug, input_tokens, output_tokens, total_tokens, context_pct, source_file, cwd)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now,
                    project_slug,
                    inp,
                    out,
                    total,
                    context_pct,
                    source_file,
                    cwd
                ))
                conn.commit()
                return True
            except sqlite3.Error as e:
                raise StorageError(f"Failed to record snapshot: {e}")

    def get_usage_history(
        self,
        days: int = 7,
        project_slug: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve usage history for graphing.

        Args:
            days: Number of days to look back (default 7)
            project_slug: Optional filter for specific project

        Returns:
            List of snapshots sorted by timestamp ascending
        """
        cutoff = time.time() - (days * 24 * 3600)
        query = """
            SELECT timestamp, project_slug, input_tokens, output_tokens,
                   total_tokens, context_pct, cwd
            FROM snapshots
            WHERE timestamp >= ?
        """
        params = [cutoff]

        if project_slug:
            query += " AND project_slug = ?"
            params.append(project_slug)

        query += " ORDER BY timestamp ASC"

        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

    def get_project_totals(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Aggregate total tokens per project over the given time window.

        Returns:
            List of dicts: [{"project_slug": "...", "total_tokens": N, "session_count": M}, ...]
        """
        cutoff = time.time() - (days * 24 * 3600)
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT project_slug,
                       SUM(total_tokens) as total_tokens,
                       COUNT(*) as session_count
                FROM snapshots
                WHERE timestamp >= ?
                GROUP BY project_slug
                ORDER BY total_tokens DESC
            """, (cutoff,))
            rows = cursor.fetchall()

            return [
                {"project_slug": row[0], "total_tokens": row[1], "session_count": row[2]}
                for row in rows
            ]

    def cleanup_old_data(self) -> int:
        """
        Delete snapshots older than RETENTION_DAYS.
        Returns number of rows deleted.
        """
        cutoff = time.time() - (RETENTION_DAYS * 24 * 3600)
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount

    def _slugify(self, name: str) -> str:
        """Convert a project name to a filesystem-safe slug."""
        return name.lower().replace(" ", "-").replace("/", "-").replace("\\", "-")[:100]


# Convenience singleton for app-wide use
_storage_instance: Optional[SQLiteStorage] = None


def get_storage() -> SQLiteStorage:
    """Get or create the global storage instance."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = SQLiteStorage()
    return _storage_instance
