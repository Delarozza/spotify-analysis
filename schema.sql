-- Run against your Spotify database (e.g. psql or DataGrip).

CREATE TABLE IF NOT EXISTS fetch_run (
    id         BIGSERIAL PRIMARY KEY,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS top_track_entry (
    id                BIGSERIAL PRIMARY KEY,
    run_id            BIGINT NOT NULL REFERENCES fetch_run (id) ON DELETE CASCADE,
    rank              SMALLINT NOT NULL,
    spotify_track_id  TEXT NOT NULL,
    track_name        TEXT NOT NULL,
    artist_name       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_top_track_entry_run ON top_track_entry (run_id);

CREATE TABLE IF NOT EXISTS listening_day_snapshot (
    day_date       DATE PRIMARY KEY,
    captured_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_plays    INT NOT NULL,
    unique_tracks  INT NOT NULL,
    tracks_json    JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listening_day_captured ON listening_day_snapshot (captured_at DESC);
