"""Local UI: top snapshots from PostgreSQL + recent listening from Spotify."""

import os
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, render_template, request, url_for
from psycopg.rows import dict_row

from db_storage import (
    fetch_listening_day_snapshot,
    get_connection,
    list_listening_snapshot_dates,
)
from listening_profile import build_listening_profile
from listening_sort import (
    LISTEN_SORT_KEYS,
    listen_sort_caption,
    next_listen_sort,
    sort_ranked_list,
)
from recent_history import (
    aggregate_by_track,
    fetch_recent_plays_between,
    get_spotify,
    window_today_local,
)

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

app = Flask(__name__)


def _fetch_latest_run(conn):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, fetched_at FROM fetch_run ORDER BY id DESC LIMIT 1"
        )
        return cur.fetchone()


def _fetch_tracks(conn, run_id: int):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT rank, track_name, artist_name, spotify_track_id
            FROM top_track_entry
            WHERE run_id = %s
            ORDER BY rank
            """,
            (run_id,),
        )
        return cur.fetchall()


def _artist_counts(tracks):
    counts = {}
    for t in tracks:
        a = t["artist_name"] or "?"
        counts[a] = counts.get(a, 0) + 1
    return sorted(counts.items(), key=lambda x: (-x[1], x[0]))


@app.route("/")
def index():
    if not os.environ.get("DATABASE_URL"):
        return render_template(
            "index.html",
            error="DATABASE_URL is not set in .env — the web UI needs a database.",
            tracks=[],
            artist_labels=[],
            artist_values=[],
        )

    try:
        with get_connection() as conn:
            latest = _fetch_latest_run(conn)
            if not latest:
                return render_template(
                    "index.html",
                    error=None,
                    tracks=[],
                    artist_labels=[],
                    artist_values=[],
                    empty=True,
                )

            tracks = _fetch_tracks(conn, latest["id"])
            artist_chart = _artist_counts(tracks)
            artist_labels = [a for a, _ in artist_chart]
            artist_values = [c for _, c in artist_chart]

            return render_template(
                "index.html",
                error=None,
                tracks=tracks,
                artist_labels=artist_labels,
                artist_values=artist_values,
                empty=False,
            )
    except Exception as e:
        return render_template(
            "index.html",
            error=f"Could not connect to the database: {e}",
            tracks=[],
            artist_labels=[],
            artist_values=[],
        )


def _artist_totals_from_ranked(ranked: list[dict]) -> tuple[list[str], list[int]]:
    by_artist: dict[str, int] = defaultdict(int)
    for row in ranked:
        by_artist[row["artist"]] += row["plays"]
    pairs = sorted(by_artist.items(), key=lambda x: (-x[1], x[0]))[:20]
    return [p[0] for p in pairs], [p[1] for p in pairs]


@app.route("/listening")
def listening():
    sort = request.args.get("sort", "plays")
    dir_ = request.args.get("dir", "desc")
    if sort not in LISTEN_SORT_KEYS:
        sort = "plays"
    if dir_ not in ("asc", "desc"):
        dir_ = "desc"

    ctx = {
        "period_label": "Today",
        "error": None,
        "empty": False,
        "window_label": "",
        "total_plays": 0,
        "unique_tracks": 0,
        "ranked": [],
        "artist_labels": [],
        "artist_values": [],
        "sort": sort,
        "sort_dir": dir_,
        "sort_urls": {},
        "sort_caption": listen_sort_caption(sort, dir_),
        "profile": None,
    }

    start, end = window_today_local()

    ctx["window_label"] = (
        f"{start.strftime('%Y-%m-%d %H:%M')} — {end.strftime('%Y-%m-%d %H:%M')} (local time)"
    )

    try:
        sp = get_spotify()
    except Exception as e:
        ctx["error"] = (
            f"{e}. Run `python spotify.py` once from the project folder "
            "so a Spotify token file `.cache` is created."
        )
        return render_template("listening.html", **ctx)

    try:
        rows = fetch_recent_plays_between(start, end, sp=sp)
    except Exception as e:
        ctx["error"] = f"Spotify API: {e}"
        return render_template("listening.html", **ctx)

    if not rows:
        ctx["empty"] = True
        return render_template("listening.html", **ctx)

    ranked = aggregate_by_track(rows)
    ranked = sort_ranked_list(ranked, sort, dir_)
    labels, values = _artist_totals_from_ranked(ranked)

    sort_urls = {
        col: url_for(
            "listening",
            sort=ns,
            dir=nd,
        )
        for col in LISTEN_SORT_KEYS
        for ns, nd in (next_listen_sort(col, sort, dir_),)
    }

    ctx["total_plays"] = len(rows)
    ctx["unique_tracks"] = len(ranked)
    ctx["ranked"] = ranked
    ctx["artist_labels"] = labels
    ctx["artist_values"] = values
    ctx["sort_urls"] = sort_urls
    ctx["profile"] = build_listening_profile(
        rows,
        sp,
        local_date_key=start.date().isoformat(),
    )
    return render_template("listening.html", **ctx)


@app.route("/listening/archive")
def listening_archive():
    if not os.environ.get("DATABASE_URL"):
        return render_template(
            "listening_archive.html",
            error="DATABASE_URL is not set — archive needs PostgreSQL.",
            days=[],
        )
    try:
        with get_connection() as conn:
            days = list_listening_snapshot_dates(conn)
        return render_template("listening_archive.html", error=None, days=days)
    except Exception as e:
        return render_template(
            "listening_archive.html",
            error=f"Could not load archive: {e}",
            days=[],
        )


@app.route("/listening/day/<date_str>")
def listening_day_archive(date_str: str):
    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        abort(404)

    sort = request.args.get("sort", "plays")
    dir_ = request.args.get("dir", "desc")
    if sort not in LISTEN_SORT_KEYS:
        sort = "plays"
    if dir_ not in ("asc", "desc"):
        dir_ = "desc"

    ctx = {
        "day_label": day.isoformat(),
        "captured_label": "",
        "error": None,
        "empty": False,
        "total_plays": 0,
        "unique_tracks": 0,
        "ranked": [],
        "artist_labels": [],
        "artist_values": [],
        "sort": sort,
        "sort_dir": dir_,
        "sort_urls": {},
        "sort_caption": listen_sort_caption(sort, dir_),
    }

    if not os.environ.get("DATABASE_URL"):
        ctx["error"] = "DATABASE_URL is not set — archive needs PostgreSQL."
        return render_template("listening_day_archive.html", **ctx)

    try:
        with get_connection() as conn:
            row = fetch_listening_day_snapshot(conn, day)
    except Exception as e:
        ctx["error"] = f"Could not load snapshot: {e}"
        return render_template("listening_day_archive.html", **ctx)

    if not row:
        ctx["empty"] = True
        return render_template("listening_day_archive.html", **ctx)

    ranked = list(row["tracks_json"] or [])
    ranked = sort_ranked_list(ranked, sort, dir_)
    labels, values = _artist_totals_from_ranked(ranked)

    ca = row["captured_at"]
    if hasattr(ca, "astimezone"):
        ca = ca.astimezone()
    ctx["captured_label"] = ca.strftime("%Y-%m-%d %H:%M")

    sort_urls = {
        col: url_for(
            "listening_day_archive",
            date_str=day.isoformat(),
            sort=ns,
            dir=nd,
        )
        for col in LISTEN_SORT_KEYS
        for ns, nd in (next_listen_sort(col, sort, dir_),)
    }

    ctx["total_plays"] = row["total_plays"]
    ctx["unique_tracks"] = row["unique_tracks"]
    ctx["ranked"] = ranked
    ctx["artist_labels"] = labels
    ctx["artist_values"] = values
    ctx["sort_urls"] = sort_urls
    return render_template("listening_day_archive.html", **ctx)


def _should_run_background_jobs() -> bool:
    return (not app.debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true")


if _should_run_background_jobs():
    from listening_scheduler import init_listening_snapshot_scheduler

    init_listening_snapshot_scheduler(app)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=True)
