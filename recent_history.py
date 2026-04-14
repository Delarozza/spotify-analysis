"""Recently played from the Spotify API (user's local time)."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyOAuth

_ROOT = Path(__file__).resolve().parent
_SCOPE = "user-top-read user-read-recently-played"

_spotify: spotipy.Spotify | None = None


def _parse_played_at(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def get_spotify() -> spotipy.Spotify:
    global _spotify
    if _spotify is None:
        for key in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI"):
            if not os.environ.get(key):
                raise RuntimeError(
                    f"Missing {key} in the environment. Add it to .env next to the project."
                )
        _spotify = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=os.environ["SPOTIPY_CLIENT_ID"],
                client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
                redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
                scope=_SCOPE,
                cache_path=str(_ROOT / ".cache"),
                open_browser=False,
            )
        )
    return _spotify


def fetch_recent_plays_between(
    start_local: datetime,
    end_local: datetime,
    *,
    sp: spotipy.Spotify | None = None,
) -> list[dict[str, Any]]:
    """
    Recently-played items whose played_at falls in [start_local, end_local] (inclusive).
    Both datetimes must use the same tzinfo (usually the local zone).
    """
    if start_local.tzinfo is None or end_local.tzinfo is None:
        raise ValueError("start_local and end_local must be timezone-aware")
    tz = start_local.tzinfo
    sp = sp or get_spotify()

    collected: list[dict[str, Any]] = []
    before_ms: int | None = None

    while True:
        kwargs: dict[str, Any] = {"limit": 50}
        if before_ms is not None:
            kwargs["before"] = before_ms
        batch = sp.current_user_recently_played(**kwargs)
        items = batch.get("items") or []
        if not items:
            break

        for row in items:
            if not row.get("track") or row["track"].get("id") is None:
                continue
            played_local = _parse_played_at(row["played_at"]).astimezone(tz)
            if start_local <= played_local <= end_local:
                collected.append(row)

        oldest = _parse_played_at(items[-1]["played_at"]).astimezone(tz)
        if oldest < start_local:
            break

        last_utc = _parse_played_at(items[-1]["played_at"])
        before_ms = int(last_utc.timestamp() * 1000)

    return collected


def window_today_local() -> tuple[datetime, datetime]:
    tz = datetime.now().astimezone().tzinfo
    now = datetime.now(tz)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start, now


def window_calendar_day_local(day: date) -> tuple[datetime, datetime]:
    """Full calendar day [00:00:00 .. 23:59:59.999999] in the machine local zone."""
    tz = datetime.now().astimezone().tzinfo
    start = datetime(day.year, day.month, day.day, 0, 0, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    return start, end


def aggregate_by_track(
    rows: list[dict[str, Any]],
    *,
    tzinfo: tzinfo | None = None,
) -> list[dict[str, Any]]:
    """Sort by play count desc; last_played is the last play time in tzinfo (default: local now)."""
    if not rows:
        return []

    tz = tzinfo or datetime.now().astimezone().tzinfo
    counts: dict[str, int] = defaultdict(int)
    last_label: dict[str, str] = {}
    tracks: dict[str, dict[str, Any]] = {}

    for row in sorted(rows, key=lambda r: r["played_at"], reverse=True):
        t = row["track"]
        tid = t["id"]
        counts[tid] += 1
        if tid not in last_label:
            pt = _parse_played_at(row["played_at"]).astimezone(tz)
            last_label[tid] = pt.strftime("%Y-%m-%d %H:%M")
        tracks[tid] = t

    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    out = []
    for tid, n in ranked:
        t = tracks[tid]
        artist = t["artists"][0]["name"] if t.get("artists") else "?"
        out.append(
            {
                "track_id": tid,
                "name": t["name"],
                "artist": artist,
                "plays": n,
                "last_played": last_label[tid],
            }
        )
    return out
