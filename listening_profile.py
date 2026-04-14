"""Playful «today's listening» summary + daily quote (Listening page)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

# Deterministic per calendar day (local date string).
_DAILY_QUOTES: list[tuple[str, str]] = [
    ("Music is the shorthand of emotion.", "Leo Tolstoy"),
    ("Where words fail, music speaks.", "Hans Christian Andersen"),
    ("Without music, life would be a mistake.", "Friedrich Nietzsche"),
    ("People haven't always been there for me but music always has.", "Taylor Swift"),
    ("If I should ever die, God forbid, let this be my epitaph: the only proof he needed for the existence of god is music.", "Kurt Vonnegut"),
    ("One good thing about music, when it hits you, you feel no pain.", "Bob Marley"),
    ("Music produces a kind of pleasure which human nature cannot do without.", "Confucius"),
    ("I like beautiful melodies telling me terrible things.", "Tom Waits"),
    ("The music is not in the notes, but in the silence between.", "Wolfgang Amadeus Mozart"),
    ("Turn up the volume, ignore the to-do list.", "Internet wisdom"),
    ("Today's mood: sponsored by the shuffle button.", "Anonymous"),
    ("If in doubt, add more bass.", "Studio folklore"),
    ("Life is short; the playlist is long.", "Anonymous"),
    ("Rhythm is a dancer — ask your neighbors.", "Anonymous"),
    ("Headphones on, world off.", "Anonymous"),
]


def _artist_weights(raw_rows: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, str]]:
    """Primary Spotify artist id -> play count today; id -> display name."""
    weights: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for item in raw_rows:
        t = item.get("track") or {}
        artists = t.get("artists") or []
        if not artists:
            continue
        a0 = artists[0]
        aid = a0.get("id")
        if not aid:
            continue
        weights[aid] += 1
        names[aid] = a0.get("name") or "?"
    return dict(weights), names


def _fetch_artist_genres(sp: Any, artist_ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i in range(0, len(artist_ids), 50):
        chunk = artist_ids[i : i + 50]
        try:
            data = sp.artists(chunk)
        except Exception:
            continue
        for a in data.get("artists") or []:
            if a and a.get("id"):
                out[a["id"]] = a.get("genres") or []
    return out


def _genre_scores(weights: dict[str, int], genres_by_artist: dict[str, list[str]]) -> list[tuple[str, int]]:
    scores: dict[str, int] = defaultdict(int)
    for aid, w in weights.items():
        for g in genres_by_artist.get(aid, ()):
            scores[g] += w
    return sorted(scores.items(), key=lambda x: (-x[1], x[0].lower()))


def _pick_quote(local_date_key: str) -> tuple[str, str]:
    digest = hashlib.sha256(local_date_key.encode()).digest()
    idx = int.from_bytes(digest[:4], "big") % len(_DAILY_QUOTES)
    return _DAILY_QUOTES[idx]


def _vibe_line(
    *,
    n_plays: int,
    n_tracks: int,
    top_genres: list[tuple[str, int]],
    top_artist: str | None,
) -> str:
    if n_tracks <= 0:
        return "Silence is also a genre — today it's winning."
    ratio = n_tracks / n_plays
    if ratio < 0.35 and n_plays >= 6:
        return "Repeat offender energy: a few songs on heavy rotation."
    if ratio > 0.75 and n_tracks >= 5:
        return "Buffet mode: you grazed across many different tracks."
    if top_genres:
        g = top_genres[0][0].lower()
        if "metal" in g or "hardcore" in g:
            return "Neighborhood alert level: politely elevated."
        if "jazz" in g or "bebop" in g:
            return "Sophisticated palette — the coffee probably tasted better too."
        if "classical" in g or "baroque" in g:
            return "Big brain soundtrack. Candles optional but recommended."
        if "pop" in g:
            return "Hooks first, questions later — a perfectly valid strategy."
        if "hip hop" in g or "rap" in g:
            return "Bars over breakfast — a solid nutritional choice."
        if "electronic" in g or "house" in g or "techno" in g:
            return "BPM-driven life choices. The floor is lava (metaphorically)."
    if top_artist and n_plays >= 5:
        return f"If today had a sponsor, it might be «{top_artist}»."
    return "Eclectic but honest — the algorithm didn't write this, you did."


def build_listening_profile(
    raw_rows: list[dict[str, Any]],
    sp: Any,
    *,
    local_date_key: str,
) -> dict[str, Any]:
    """
    Returns keys: bullets (list[str]), quote (str), quote_author (str).
    Safe on empty raw_rows (still returns a quote).
    """
    weights, id_to_name = _artist_weights(raw_rows)
    n_plays = len(raw_rows)
    n_tracks = len({(item.get("track") or {}).get("id") for item in raw_rows if (item.get("track") or {}).get("id")})

    genres_by_artist: dict[str, list[str]] = {}
    if weights:
        genres_by_artist = _fetch_artist_genres(sp, list(weights.keys()))

    genre_ranked = _genre_scores(weights, genres_by_artist)
    top_genres = genre_ranked[:5]

    top_artist_name: str | None = None
    if weights:
        top_id = max(weights, key=lambda k: (weights[k], id_to_name.get(k, "")))
        top_artist_name = id_to_name.get(top_id)

    vibe = _vibe_line(
        n_plays=n_plays,
        n_tracks=n_tracks,
        top_genres=top_genres,
        top_artist=top_artist_name,
    )

    bullets: list[str] = []
    bullets.append(f"Plays logged today: {n_plays} — unique tracks: {n_tracks}.")
    if top_artist_name:
        bullets.append(f"Main character (most plays from one artist): {top_artist_name}.")
    if top_genres:
        g1, s1 = top_genres[0]
        bullets.append(f"Genre radar: «{g1}» leads the scoreboard ({s1} weighted plays).")
        if len(top_genres) > 1:
            rest = ", ".join(f"{g} ({s})" for g, s in top_genres[1:3])
            bullets.append(f"Honorable mentions: {rest}.")
    else:
        bullets.append("Genre radar: Spotify stayed mysterious — no genre tags for these artists.")

    bullets.append(vibe)

    quote, author = _pick_quote(local_date_key)

    return {
        "bullets": bullets,
        "quote": quote,
        "quote_author": author,
    }
