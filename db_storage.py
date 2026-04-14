import os
from datetime import date
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def get_connection() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Set DATABASE_URL, e.g. "
            "postgresql://USER:PASSWORD@localhost:5432/spotify"
        )
    return psycopg.connect(url)


def _top_entry_rows(run_id: int, items: list[dict[str, Any]]) -> list[tuple]:
    return [
        (
            run_id,
            idx,
            item["id"],
            item["name"],
            item["artists"][0]["name"] if item.get("artists") else "",
        )
        for idx, item in enumerate(items, start=1)
    ]


def save_top_tracks(conn: psycopg.Connection, items: list[dict[str, Any]]) -> int:
    """Persist one top snapshot. Returns run_id."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO fetch_run DEFAULT VALUES RETURNING id")
        run_id = cur.fetchone()[0]
        cur.executemany(
            """
            INSERT INTO top_track_entry
                (run_id, rank, spotify_track_id, track_name, artist_name)
            VALUES (%s, %s, %s, %s, %s)
            """,
            _top_entry_rows(run_id, items),
        )
    conn.commit()
    return run_id


def delete_fetch_run(conn: psycopg.Connection, run_id: int) -> bool:
    """Delete a snapshot; top_track_entry rows cascade. Returns True if the id existed."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM fetch_run WHERE id = %s RETURNING id", (run_id,))
        row = cur.fetchone()
    conn.commit()
    return row is not None


def fetch_latest_run_id(conn: psycopg.Connection) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM fetch_run ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return int(row[0]) if row else None


def replace_top_tracks(conn: psycopg.Connection, run_id: int, items: list[dict[str, Any]]) -> None:
    """Replace top rows for run_id, bump fetched_at, insert the new top."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM fetch_run WHERE id = %s", (run_id,))
        if cur.fetchone() is None:
            raise ValueError(f"Snapshot fetch_run.id = {run_id} not found.")
        cur.execute("DELETE FROM top_track_entry WHERE run_id = %s", (run_id,))
        cur.execute(
            "UPDATE fetch_run SET fetched_at = now() WHERE id = %s",
            (run_id,),
        )
        cur.executemany(
            """
            INSERT INTO top_track_entry
                (run_id, rank, spotify_track_id, track_name, artist_name)
            VALUES (%s, %s, %s, %s, %s)
            """,
            _top_entry_rows(run_id, items),
        )
    conn.commit()


def upsert_listening_day_snapshot(
    conn: psycopg.Connection,
    day_date: date,
    total_plays: int,
    unique_tracks: int,
    tracks: list[dict[str, Any]],
) -> None:
    """Save or replace the end-of-day listening summary for a calendar date."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO listening_day_snapshot
                (day_date, total_plays, unique_tracks, tracks_json)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (day_date) DO UPDATE SET
                captured_at = now(),
                total_plays = EXCLUDED.total_plays,
                unique_tracks = EXCLUDED.unique_tracks,
                tracks_json = EXCLUDED.tracks_json
            """,
            (day_date, total_plays, unique_tracks, Json(tracks)),
        )
    conn.commit()


def fetch_listening_day_snapshot(conn: psycopg.Connection, day_date: date) -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT day_date, captured_at, total_plays, unique_tracks, tracks_json
            FROM listening_day_snapshot
            WHERE day_date = %s
            """,
            (day_date,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def list_listening_snapshot_dates(conn: psycopg.Connection) -> list[date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT day_date FROM listening_day_snapshot ORDER BY day_date DESC"
        )
        return [r[0] for r in cur.fetchall()]
