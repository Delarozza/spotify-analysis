"""Daily listening snapshots (PostgreSQL + Spotify Recently Played)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def capture_listening_day(
    sp: Any,
    conn: Any,
    day: date,
    tz: ZoneInfo,
    *,
    end_mode: str = "auto",
) -> tuple[int, int]:
    """
    Fetch plays for calendar ``day`` in ``tz``, aggregate, upsert into ``listening_day_snapshot``.

    ``end_mode``:
      - ``"now"``: window is [day 00:00 .. current time] (same calendar day only).
      - ``"end_of_day"``: full local calendar day.
      - ``"auto"``: full day for past dates; for today, same as ``"now"``.
    Returns ``(total_plays, unique_tracks)``.
    """
    from db_storage import upsert_listening_day_snapshot
    from recent_history import aggregate_by_track, fetch_recent_plays_between

    start = datetime(day.year, day.month, day.day, 0, 0, 0, 0, tzinfo=tz)
    today = datetime.now(tz).date()
    day_end = start + timedelta(days=1) - timedelta(microseconds=1)

    if day > today:
        logger.warning("capture_listening_day: skip future day %s", day)
        return 0, 0

    if end_mode == "now":
        end = datetime.now(tz)
        if end.date() < day:
            return 0, 0
        if end.date() > day:
            end = day_end
    elif end_mode == "end_of_day":
        end = day_end
    else:
        if day < today:
            end = day_end
        elif day == today:
            end = datetime.now(tz)
            if end < start:
                upsert_listening_day_snapshot(conn, day, 0, 0, [])
                return 0, 0

    if end < start:
        upsert_listening_day_snapshot(conn, day, 0, 0, [])
        return 0, 0

    rows = fetch_recent_plays_between(start, end, sp=sp)
    ranked = aggregate_by_track(rows, tzinfo=tz)
    upsert_listening_day_snapshot(conn, day, len(rows), len(ranked), ranked)
    logger.info(
        "listening snapshot saved day=%s plays=%s unique=%s",
        day,
        len(rows),
        len(ranked),
    )
    return len(rows), len(ranked)


def run_scheduled_listening_snapshot(sp: Any, conn: Any, tz: ZoneInfo) -> None:
    """Default schedule 00:05 in ``tz``: persist *yesterday* as a full calendar day."""
    yesterday = (datetime.now(tz) - timedelta(days=1)).date()
    capture_listening_day(sp, conn, yesterday, tz, end_mode="end_of_day")
