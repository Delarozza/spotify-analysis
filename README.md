# Spotify project: top tracks in PostgreSQL and “what I listened to today”

A small Python app: **snapshots of your Spotify top tracks** are stored in a database and shown in a web UI; **plays from today** (local midnight → now) come from the Recently Played API on a separate page (and optionally in the terminal).

## Features

| What | Data source | Where to view |
|------|-------------|---------------|
| Top tracks (~6 months, `medium_term`) | Spotify API when you run the script | Home `/` — **latest** snapshot from the DB: table + artist chart |
| Listening today | Spotify Recently Played | `/listening` — aggregated from **local** midnight to now |

**Note:** Recently Played is **not** a full play history. The API has limits; the Listening page only reflects what the API returned for the requested window.

## Requirements

- Python **3.10+** (uses modern type hints).
- A [Spotify Developer](https://developer.spotify.com/dashboard) app (Client ID / Client Secret).
- **PostgreSQL** only if you want top snapshots in the DB and the Top page. For `python spotify.py --today` alone, no database is required.

## Setup

```bash
cd spotify-project
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy the environment template and fill in your values:

```bash
cp .env.example .env
```

### Environment variables (`.env`)

| Variable | Required | Purpose |
|----------|----------|---------|
| `SPOTIPY_CLIENT_ID` | Yes | Spotify app client ID |
| `SPOTIPY_CLIENT_SECRET` | Yes | Spotify app client secret |
| `SPOTIPY_REDIRECT_URI` | Yes | OAuth redirect URI; **must match** the value in the Spotify app settings (e.g. `http://127.0.0.1:8888/callback` as in the example) |
| `DATABASE_URL` | For DB-backed top + home page | PostgreSQL URL, e.g. `postgresql://user:pass@localhost:5432/spotify` |

Spotipy creates **`.cache`** in the project root after a successful login — do not commit it (keep it in `.gitignore`). Without it, the Listening page will suggest running `python spotify.py` once.

### Database (for “Top”)

1. Create a PostgreSQL database.
2. Run `schema.sql` (psql, DataGrip, etc.) — creates `fetch_run` and `top_track_entry`.
3. Set `DATABASE_URL` in `.env`.

## Spotify Developer checklist

1. Create an **App** in the Dashboard.
2. Under **Redirect URIs**, add the **exact** URI from `SPOTIPY_REDIRECT_URI`.
3. Scopes used in code: `user-top-read`, `user-read-recently-played` (OAuth will request them on first sign-in).

## CLI: `spotify.py`

Run from the `spotify-project` directory so `.env` next to the script is loaded.

```bash
python spotify.py
```

By default:

- Fetches top **10** tracks for **medium_term** (~6 months).
- Prints the list and a short artist breakdown for that top 10.
- If `DATABASE_URL` is set, writes a **new** snapshot to PostgreSQL (`fetch_run` + `top_track_entry` rows).

**Overwrite an existing snapshot** (same `fetch_run.id`, new tracks, `fetched_at` updated):

```bash
python spotify.py --overwrite-run 3
```

Use the `fetch_run.id` from the script output after a save or from the database.

Overwrite the **latest** snapshot by id:

```bash
python spotify.py --overwrite-latest
```

If there are no snapshots yet, `--overwrite-latest` prints a hint to create the first one with plain `python spotify.py`.

**Delete a snapshot** (one `fetch_run` row and its `top_track_entry` rows — schema uses `ON DELETE CASCADE`):

```bash
python spotify.py --delete-run 3
```

Does not call Spotify; only `DATABASE_URL` is required. Cannot be combined with `--today` or overwrite flags.

Same in SQL: `DELETE FROM fetch_run WHERE id = 3;` — child tracks cascade. Delete all snapshots: `DELETE FROM fetch_run;`.

**Today’s listening** (local calendar day):

```bash
python spotify.py --today
# or:
python spotify.py -t
```

Uses only Recently Played; **not** written to the top tables.

On first run, a browser may open (or follow the terminal) to sign in to Spotify — then `.cache` appears.

**Daily listening archive** (optional, PostgreSQL table `listening_day_snapshot`):

- Apply the new block from `schema.sql` (same DB as the top feature).
- Set `LISTENING_SNAPSHOT_TZ` to your IANA timezone (e.g. `Europe/Berlin`). Optionally `LISTENING_SNAPSHOT_AT=00:05` (default **`00:05`**).
- While **`webapp.py` is running**, a job fires once per day at that time and stores **yesterday’s** full calendar day (00:00–23:59:59 in that zone), so nothing is cut off at the last minute of the evening.
- **CLI backfill / cron without the web server:**

```bash
python spotify.py --snapshot-day 2026-04-14
python spotify.py --snapshot-yesterday
```

- In the browser: **Archive** lists saved dates; each opens as a frozen table (no live Spotify call).

## Web UI: `webapp.py`

```bash
python webapp.py
```

Default URL: **http://127.0.0.1:5050**

| URL | Description |
|-----|-------------|
| `/` | **Top:** latest snapshot from the DB, track table, artist chart. Without `DATABASE_URL`, shows a configuration error. |
| `/listening` | **Listening:** today’s stats from the Spotify API. Needs Spotipy env vars and `.cache` (after at least one successful auth via `spotify.py` or OAuth using the same `cache_path`). |
| `/listening/archive` | **Archive:** list of saved daily listening snapshots (`DATABASE_URL` + table from `schema.sql`). |
| `/listening/day/<YYYY-MM-DD>` | One saved day (read-only, from the DB). |

Stop with `Ctrl+C`.

## Project layout (short)

| Path | Role |
|------|------|
| `spotify.py` | CLI: top + optional DB write; “today” mode. |
| `webapp.py` | Flask app, routes `/`, `/listening`, archive. |
| `listening_snapshots.py` | Capture one calendar day into `listening_day_snapshot`. |
| `listening_scheduler.py` | Optional APScheduler hook when `webapp.py` runs. |
| `listening_sort.py` | Shared column sort for live + archive tables. |
| `recent_history.py` | “Today” window, recently played fetch, per-track aggregation. |
| `db_storage.py` | PostgreSQL connection and snapshot persistence. |
| `schema.sql` | Table definitions for snapshots. |
| `templates/`, `static/` | Web UI. |

## FAQ

**Why is Listening empty or not matching what I played?**  
Data comes from the recently played endpoint; coverage is limited. It is not a full streaming log.

**Home says there are no snapshots**  
Run `python spotify.py` at least once with `DATABASE_URL` set and the schema applied.

**Redirect / invalid `redirect_uri`**  
The Spotify Dashboard value and `SPOTIPY_REDIRECT_URI` must match **exactly** (scheme, host, port, path).

**Token / Listening won’t load**  
Authorize once with `python spotify.py` (or delete an expired `.cache` and sign in again on the next run).

## License and data

Personal use. Do not publish `.env`, `.cache`, or database passwords. Spotify and PostgreSQL data stay on your machine.
