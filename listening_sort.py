"""Shared table sorting for Listening (live + archive)."""

from __future__ import annotations

LISTEN_SORT_KEYS = frozenset({"plays", "track", "artist", "last"})


def next_listen_sort(column: str, current_sort: str, current_dir: str) -> tuple[str, str]:
    defaults = {"plays": "desc", "track": "asc", "artist": "asc", "last": "desc"}
    if current_sort == column:
        return column, "asc" if current_dir == "desc" else "desc"
    return column, defaults[column]


def sort_ranked_list(rows: list[dict], sort: str, direction: str) -> list[dict]:
    if not rows:
        return []
    sort = sort if sort in LISTEN_SORT_KEYS else "plays"
    desc = direction == "desc"
    if sort == "plays":
        return sorted(rows, key=lambda r: r["plays"], reverse=desc)
    if sort == "track":
        return sorted(rows, key=lambda r: (r["name"] or "").lower(), reverse=desc)
    if sort == "artist":
        return sorted(rows, key=lambda r: (r["artist"] or "").lower(), reverse=desc)
    return sorted(rows, key=lambda r: r["last_played"], reverse=desc)


def listen_sort_caption(sort: str, dir_: str) -> str:
    names = {
        "plays": "play count",
        "track": "track title",
        "artist": "artist",
        "last": "last played",
    }
    order = "descending" if dir_ == "desc" else "ascending"
    return f"Sorted by {names.get(sort, 'play count')} ({order})"
