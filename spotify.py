import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from recent_history import (
    aggregate_by_track,
    fetch_recent_plays_between,
    window_today_local,
)

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

_REQUIRED_SPOTIFY = ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI")
_SCOPE = "user-top-read user-read-recently-played"

_spotify_client: spotipy.Spotify | None = None


def _spotify() -> spotipy.Spotify:
    global _spotify_client
    missing = [k for k in _REQUIRED_SPOTIFY if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing environment variables: {', '.join(missing)}. "
            f"Create {_ROOT / '.env'} (see .env.example) or export them in your shell."
        )
    if _spotify_client is None:
        _spotify_client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=os.environ["SPOTIPY_CLIENT_ID"],
                client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
                redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
                scope=_SCOPE,
                cache_path=str(_ROOT / ".cache"),
            )
        )
    return _spotify_client


def _print_top_report(results: dict) -> None:
    items = results["items"]
    print("🎧 Your top tracks (~6 mo., medium_term):\n")

    for i, item in enumerate(items, 1):
        track_name = item["name"]
        artist = item["artists"][0]["name"]
        print(f"{i}. {track_name} — {artist}")

    artists_count: dict[str, int] = {}
    for item in items:
        artist = item["artists"][0]["name"]
        artists_count[artist] = artists_count.get(artist, 0) + 1

    print("\n🔥 Artists in this top 10:\n")
    for artist, count in sorted(artists_count.items(), key=lambda x: x[1], reverse=True):
        print(f"{artist}: {count} tracks")


def run_top_tracks(*, overwrite_run_id: int | None = None, overwrite_latest: bool = False) -> None:
    results = _spotify().current_user_top_tracks(limit=10, time_range="medium_term")
    _print_top_report(results)

    if not os.environ.get("DATABASE_URL"):
        if overwrite_run_id is not None or overwrite_latest:
            print("\n⚠️  DATABASE_URL must be set in .env to update a snapshot in the database.")
        return

    from db_storage import (
        fetch_latest_run_id,
        get_connection,
        replace_top_tracks,
        save_top_tracks,
    )

    with get_connection() as conn:
        if overwrite_latest:
            rid = fetch_latest_run_id(conn)
            if rid is None:
                print("\n⚠️  No snapshots in the DB yet — create the first with: python spotify.py")
                return
            replace_top_tracks(conn, rid, results["items"])
            print(f"\n💾 Snapshot #{rid} overwritten with the latest top (fetch_run.fetched_at updated).")
        elif overwrite_run_id is not None:
            replace_top_tracks(conn, overwrite_run_id, results["items"])
            print(
                f"\n💾 Snapshot #{overwrite_run_id} overwritten with the latest top "
                "(fetch_run.fetched_at updated)."
            )
        else:
            run_id = save_top_tracks(conn, results["items"])
            print(f"\n💾 New top snapshot saved to PostgreSQL (fetch_run.id = {run_id}).")


def run_delete_run(run_id: int) -> None:
    if not os.environ.get("DATABASE_URL"):
        print("⚠️  DATABASE_URL must be set in .env to delete snapshots.")
        return
    from db_storage import delete_fetch_run, get_connection

    with get_connection() as conn:
        ok = delete_fetch_run(conn, run_id)
    if ok:
        print(f"🗑️  Snapshot #{run_id} removed from PostgreSQL (including tracks).")
    else:
        print(f"Snapshot #{run_id} was not found in the database.")


def run_today() -> None:
    start, end = window_today_local()
    rows = fetch_recent_plays_between(start, end, sp=_spotify())
    if not rows:
        print("Nothing in recently played for today (local time) yet.")
        print("(This is not Spotify's official “top”; it's what the API reports you played.)")
        return

    ranked = aggregate_by_track(rows)

    print(f"📅 Today: {len(rows)} plays, {len(ranked)} unique tracks\n")

    for i, item in enumerate(ranked[:20], 1):
        print(f"{i}. {item['name']} — {item['artist']}  ({item['plays']}×)")

    if len(ranked) > 20:
        print(f"\n… and {len(ranked) - 20} more tracks")

    print(
        "\n(Data from Recently Played; history depth is limited by the API. "
        "This is not saved as a “top” snapshot in the database.)"
    )


def run_listening_snapshot_day(day: date) -> None:
    if not os.environ.get("DATABASE_URL"):
        print("⚠️  DATABASE_URL must be set in .env to save listening snapshots.")
        return
    tz_name = (os.environ.get("LISTENING_SNAPSHOT_TZ") or os.environ.get("TZ") or "").strip()
    if not tz_name:
        print(
            '⚠️  Set LISTENING_SNAPSHOT_TZ (e.g. Europe/Moscow) so "calendar day" matches your life.'
        )
        return
    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:
        print(f"⚠️  Invalid timezone {tz_name!r}: {e}")
        return
    from db_storage import get_connection
    from listening_snapshots import capture_listening_day

    sp = _spotify()
    with get_connection() as conn:
        total, unique = capture_listening_day(sp, conn, day, tz, end_mode="auto")
    print(f"💾 Listening snapshot for {day.isoformat()}: {total} plays, {unique} unique tracks.")


def run_listening_snapshot_yesterday() -> None:
    tz_name = (os.environ.get("LISTENING_SNAPSHOT_TZ") or os.environ.get("TZ") or "").strip()
    if not tz_name:
        print("⚠️  Set LISTENING_SNAPSHOT_TZ (or TZ) for yesterday’s date boundary.")
        return
    tz = ZoneInfo(tz_name)
    y = (datetime.now(tz) - timedelta(days=1)).date()
    run_listening_snapshot_day(y)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Spotify: top tracks and today's listening (console)."
    )
    parser.add_argument(
        "-t",
        "--today",
        action="store_true",
        help="print what you listened to today (console only)",
    )
    parser.add_argument(
        "--delete-run",
        type=int,
        metavar="ID",
        help="delete a snapshot from the DB (no Spotify call; tracks cascade)",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument(
        "--overwrite-run",
        type=int,
        metavar="ID",
        help="overwrite an existing snapshot (same fetch_run.id, new tracks and time)",
    )
    g.add_argument(
        "--overwrite-latest",
        action="store_true",
        help="overwrite the snapshot with the highest id (latest in the app)",
    )
    snap = parser.add_mutually_exclusive_group()
    snap.add_argument(
        "--snapshot-day",
        metavar="YYYY-MM-DD",
        help="save listening_day_snapshot for that calendar date (needs DATABASE_URL + LISTENING_SNAPSHOT_TZ)",
    )
    snap.add_argument(
        "--snapshot-yesterday",
        action="store_true",
        help="same as --snapshot-day for yesterday in LISTENING_SNAPSHOT_TZ",
    )
    args = parser.parse_args()

    has_overwrite = args.overwrite_run is not None or args.overwrite_latest
    has_snap = args.snapshot_day is not None or args.snapshot_yesterday
    if sum([args.today, args.delete_run is not None, has_overwrite, has_snap]) > 1:
        parser.error(
            "use only one mode: --today, --delete-run, overwrite, snapshot, or plain run for top"
        )

    if args.delete_run is not None:
        run_delete_run(args.delete_run)
    elif args.today:
        run_today()
    elif args.snapshot_yesterday:
        run_listening_snapshot_yesterday()
    elif args.snapshot_day is not None:
        try:
            snap_day = date.fromisoformat(args.snapshot_day)
        except ValueError:
            parser.error("--snapshot-day must be YYYY-MM-DD")
        run_listening_snapshot_day(snap_day)
    else:
        run_top_tracks(
            overwrite_run_id=args.overwrite_run,
            overwrite_latest=args.overwrite_latest,
        )
