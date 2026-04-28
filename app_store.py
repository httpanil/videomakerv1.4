from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class AppStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    google_sub TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    avatar_url TEXT,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS render_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    orientation TEXT NOT NULL,
                    image_mode TEXT NOT NULL,
                    audio_duration REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    created_local_day TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    output_name TEXT,
                    error TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                );

                CREATE INDEX IF NOT EXISTS idx_render_jobs_user_day
                    ON render_jobs(user_id, created_local_day);

                CREATE INDEX IF NOT EXISTS idx_render_jobs_user_created
                    ON render_jobs(user_id, created_at DESC);
                """
            )

    def upsert_google_user(
        self,
        google_sub: str,
        email: str,
        name: str,
        avatar_url: str | None,
        now_iso: str,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM users WHERE google_sub = ?",
                (google_sub,),
            ).fetchone()

            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO users (google_sub, email, name, avatar_url, created_at, last_login_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (google_sub, email, name, avatar_url, now_iso, now_iso),
                )
                user_id = cursor.lastrowid
            else:
                connection.execute(
                    """
                    UPDATE users
                    SET email = ?, name = ?, avatar_url = ?, last_login_at = ?
                    WHERE google_sub = ?
                    """,
                    (email, name, avatar_url, now_iso, google_sub),
                )
                user_id = existing["id"]

            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row is not None else {}

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            return dict(row) if row is not None else None

    def create_render_job(
        self,
        job_id: str,
        user_id: int,
        orientation: str,
        image_mode: str,
        audio_duration: float,
        created_at: str,
        created_local_day: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO render_jobs (
                    job_id, user_id, orientation, image_mode, audio_duration,
                    created_at, created_local_day, updated_at, status, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'Waiting for a worker')
                """,
                (
                    job_id,
                    user_id,
                    orientation,
                    image_mode,
                    audio_duration,
                    created_at,
                    created_local_day,
                    created_at,
                ),
            )

    def update_render_job(
        self,
        job_id: str,
        status: str,
        message: str,
        updated_at: str,
        output_name: str | None,
        error: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE render_jobs
                SET status = ?, message = ?, updated_at = ?, output_name = ?, error = ?
                WHERE job_id = ?
                """,
                (status, message, updated_at, output_name, error, job_id),
            )

    def count_user_jobs_for_day(self, user_id: int, local_day: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM render_jobs WHERE user_id = ? AND created_local_day = ?",
                (user_id, local_day),
            ).fetchone()
            return int(row["count"]) if row is not None else 0

    def get_render_job_for_user(self, user_id: int, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM render_jobs WHERE user_id = ? AND job_id = ?",
                (user_id, job_id),
            ).fetchone()
            return dict(row) if row is not None else None

    def list_user_videos(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM render_jobs
                WHERE user_id = ? AND output_name IS NOT NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_video_by_output_name_for_user(self, user_id: int, output_name: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM render_jobs
                WHERE user_id = ? AND output_name = ?
                """,
                (user_id, output_name),
            ).fetchone()
            return dict(row) if row is not None else None
