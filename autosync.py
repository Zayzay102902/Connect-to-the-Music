"""Automatic two-way sync for "Keep Synced" playlists (platform = 'both').

This module has no imports from main.py, so the merge logic can be tested
without a database. Anything that talks to Spotify, YouTube, or Postgres is
passed in by the caller.

Track shapes used here:
  Spotify item:  {"track_id", "uri", "title", "artist"}
  YouTube item:  {"video_id", "item_id", "title", "artist"}   (item_id = playlistItem id)
  Snapshot pair: {"spotify_track_id", "youtube_video_id"}
"""

import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SPOTIFY = "spotify"
YOUTUBE = "youtube"

# Estimated YouTube Data API cost per call (units).
YT_COST_LIST = 1
YT_COST_SEARCH = 100
YT_COST_INSERT = 50
YT_COST_DELETE = 50


# ============================================================
# CONFIG
# ============================================================

def env_int(name: str, default: int):
    try:
        return max(0, int(os.getenv(name, default)))
    except ValueError:
        print(f"{name} is not a number, using default {default}")
        return default


def is_dry_run():
    # Defaults to dry run. Only an explicit false-ish value turns real writes on.
    return os.getenv("SYNC_DRY_RUN", "true").strip().lower() not in ("false", "0", "no", "off")


def max_removals():
    return env_int("SYNC_MAX_REMOVALS", 10)


def max_pairs():
    return env_int("SYNC_MAX_PAIRS", 5)


def time_budget_seconds():
    return env_int("SYNC_TIME_BUDGET_SECONDS", 20)


def max_yt_searches():
    return env_int("SYNC_MAX_YT_SEARCHES", 5)


# ============================================================
# DATABASE (the runner's own connection)
# ============================================================

def resolve_database_url():
    """A .env file next to this module wins over the process environment.

    Locally, Windows has a DATABASE_URL pointing at localhost that
    load_dotenv() won't override, so read .env directly. On Render there's
    no .env (it's gitignored), so the real environment variable is used.
    """
    env_file = Path(__file__).resolve().with_name(".env")
    if env_file.is_file():
        from dotenv import dotenv_values

        url = dotenv_values(env_file).get("DATABASE_URL")
        if url:
            return url
    return os.getenv("DATABASE_URL")


_sync_pool = None


def _get_sync_pool():
    global _sync_pool
    if _sync_pool is None:
        from psycopg2 import pool as pg_pool

        _sync_pool = pg_pool.SimpleConnectionPool(1, 3, resolve_database_url())
    return _sync_pool


@contextmanager
def sync_db_conn():
    p = _get_sync_pool()
    conn = p.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


# ============================================================
# FETCH VALIDATION
# ============================================================

def validate_fetch(label: str, result, snapshot_count: int):
    """Return an error string if this fetch can't be trusted, else None.

    `result` is the dict from fetch_*_tracks(include_ids=True), or an
    Exception if the fetch raised.
    """
    if isinstance(result, Exception):
        return f"{label} fetch failed: {type(result).__name__}: {result}"
    if not isinstance(result, dict) or not isinstance(result.get("songs"), list):
        return f"{label} fetch returned an unexpected shape"
    if result.get("truncated"):
        return f"{label} playlist is longer than the fetch limit; a partial list would look like deletions"
    if not result["songs"] and snapshot_count > 0:
        return f"{label} returned no songs but the snapshot has {snapshot_count}; refusing to treat that as 'everything deleted'"
    return None


# ============================================================
# MERGE PLAN
# ============================================================

class MatchBudgetExceeded(Exception):
    """Raised by match_fn when this run can't afford another search.
    The song is deferred to a later run, not marked unmatched."""


def _song(item):
    return {"title": item.get("title"), "artist": item.get("artist")}


def _norm(text):
    return " ".join((text or "").lower().split())


def default_same_song(a, b):
    """Strict fallback used by tests. The runner passes main.song_matches instead."""
    return bool(a.get("title") and a.get("artist")) and (
        _norm(a["title"]) == _norm(b.get("title")) and _norm(a["artist"]) == _norm(b.get("artist"))
    )


def plan_sync(
    snapshot,
    sp_tracks,
    yt_tracks,
    yt_unavailable,
    match_fn,
    recently_unmatched=frozenset(),
    removal_cap=None,
    same_song=None,
):
    """Work out what to change on each side. Makes no changes itself.

    match_fn(song, target_platform) -> (id or None, reason). It may raise
    MatchBudgetExceeded to defer the song.

    recently_unmatched: set of (platform, source_id) that failed to match
    recently. They are skipped without searching.

    same_song(a, b) -> bool says whether two {title, artist} dicts are the
    same song. Before searching for a new song, we look for it among the
    other playlist's unpaired items, so a song that's already there (maybe
    as a different upload than search would pick) is paired, not duplicated.

    Returns a dict:
      status        "ok" or "skipped_removal_cap"
      spotify_add   [track_id]           yt_add       [video_id]
      spotify_remove[{track_id, uri}]    yt_remove    [{video_id, item_id}]
      new_snapshot  [pair]               unmatched    [{platform, source_id, title, artist, reason}]
      deferred      [{platform, source_id, title, artist}]
      first_sync    bool
    """
    if removal_cap is None:
        removal_cap = max_removals()

    first_sync = len(snapshot) == 0
    yt_unavailable = set(yt_unavailable)

    sp_by_id = {}
    for t in sp_tracks:
        if t.get("track_id"):
            sp_by_id.setdefault(t["track_id"], t)
    yt_by_id = {}
    yt_item_ids = {}  # video_id -> every playlistItem id (duplicates included)
    for v in yt_tracks:
        vid = v.get("video_id")
        if not vid:
            continue
        yt_by_id.setdefault(vid, v)
        yt_item_ids.setdefault(vid, []).append(v.get("item_id"))

    snap_sp = {p["spotify_track_id"] for p in snapshot}
    snap_yt = {p["youtube_video_id"] for p in snapshot}

    kept = []                # pairs that survive unchanged
    remove_yt_candidates = {}  # video_id -> Spotify track it was paired with (now gone)
    remove_sp_candidates = {}  # track_id -> YouTube video it was paired with (now gone)

    # --- 1. Walk the snapshot: what disappeared since last sync? ---
    for pair in snapshot:
        s, y = pair["spotify_track_id"], pair["youtube_video_id"]
        s_here = s in sp_by_id
        y_here = y in yt_by_id
        y_unknown = y in yt_unavailable  # private/deleted video: can't tell if user removed it

        if s_here and (y_here or y_unknown):
            kept.append(pair)
        elif not s_here and y_here:
            remove_yt_candidates[y] = s
        elif s_here and not y_here:
            remove_sp_candidates[s] = y
        # both gone (or Spotify gone + video unavailable): just drop the pair

    new_pairs = []
    unmatched = []
    deferred = []
    sp_add, yt_add = [], []

    def paired_sp():
        return {p["spotify_track_id"] for p in kept + new_pairs}

    def paired_yt():
        return {p["youtube_video_id"] for p in kept + new_pairs}

    same_song = same_song or default_same_song

    def find_local(song, by_id, snap_ids, paired, remove_candidates):
        # Unpaired items on the other side: new since last sync, or about to
        # be removed (a version swap). Already-paired items are never reused.
        for other_id, item in by_id.items():
            if other_id in paired:
                continue
            if other_id in snap_ids and other_id not in remove_candidates:
                continue
            try:
                if same_song(song, _song(item)):
                    return other_id
            except Exception:
                continue
        return None

    # --- 2. Songs added on Spotify -> find them on YouTube ---
    for s, track in sp_by_id.items():
        if s in snap_sp or s in paired_sp():
            continue
        song = _song(track)
        local_y = None
        if song["title"] and song["artist"]:
            local_y = find_local(song, yt_by_id, snap_yt, paired_yt(), remove_yt_candidates)
        if local_y:
            remove_yt_candidates.pop(local_y, None)
            new_pairs.append({"spotify_track_id": s, "youtube_video_id": local_y})
            continue
        if (SPOTIFY, s) in recently_unmatched:
            continue
        if not song["title"] or not song["artist"]:
            unmatched.append({"platform": SPOTIFY, "source_id": s, **song, "reason": "missing title or artist"})
            continue
        try:
            y, reason = match_fn(song, YOUTUBE)
        except MatchBudgetExceeded:
            deferred.append({"platform": SPOTIFY, "source_id": s, **song})
            continue
        if not y:
            unmatched.append({"platform": SPOTIFY, "source_id": s, **song, "reason": reason or "no match"})
            continue
        if y in yt_unavailable:
            unmatched.append({"platform": SPOTIFY, "source_id": s, **song, "reason": "matched video is unavailable"})
            continue
        if y in remove_yt_candidates:
            # Spotify swapped one version of a song for another; keep the video.
            del remove_yt_candidates[y]
        elif y not in yt_by_id and y not in yt_add:
            yt_add.append(y)
        new_pairs.append({"spotify_track_id": s, "youtube_video_id": y})

    # --- 3. Songs added on YouTube -> find them on Spotify ---
    for y, video in yt_by_id.items():
        if y in snap_yt or y in paired_yt():
            continue
        song = _song(video)
        local_s = None
        if song["title"] and song["artist"]:
            local_s = find_local(song, sp_by_id, snap_sp, paired_sp(), remove_sp_candidates)
        if local_s:
            remove_sp_candidates.pop(local_s, None)
            new_pairs.append({"spotify_track_id": local_s, "youtube_video_id": y})
            continue
        if (YOUTUBE, y) in recently_unmatched:
            continue
        if not song["title"] or not song["artist"]:
            unmatched.append({"platform": YOUTUBE, "source_id": y, **song, "reason": "couldn't read an artist from the video title"})
            continue
        try:
            s, reason = match_fn(song, SPOTIFY)
        except MatchBudgetExceeded:
            deferred.append({"platform": YOUTUBE, "source_id": y, **song})
            continue
        if not s:
            unmatched.append({"platform": YOUTUBE, "source_id": y, **song, "reason": reason or "no match"})
            continue
        if s in remove_sp_candidates:
            # e.g. a manual /sync_playlist swapped the video for another upload
            # of the same song. Don't delete the Spotify track.
            del remove_sp_candidates[s]
        elif s not in sp_by_id and s not in sp_add:
            sp_add.append(s)
        new_pairs.append({"spotify_track_id": s, "youtube_video_id": y})

    # --- 4. Final removals: never remove something another pair still uses ---
    still_sp = paired_sp()
    still_yt = paired_yt()
    spotify_remove = [
        {"track_id": s, "uri": sp_by_id[s].get("uri") or f"spotify:track:{s}"}
        for s in remove_sp_candidates
        if s not in still_sp and s in sp_by_id
    ]
    yt_remove = [
        {"video_id": y, "item_id": item_id}
        for y in remove_yt_candidates
        if y not in still_yt and y in yt_by_id
        for item_id in yt_item_ids[y]
    ]

    if first_sync:
        # Belt and braces: with no snapshot there's nothing to diff against,
        # so nothing can have been "removed".
        spotify_remove, yt_remove = [], []

    plan = {
        "status": "ok",
        "first_sync": first_sync,
        "spotify_add": sp_add,
        "yt_add": yt_add,
        "spotify_remove": spotify_remove,
        "yt_remove": yt_remove,
        "new_snapshot": _dedupe_pairs(kept + new_pairs),
        "unmatched": unmatched,
        "deferred": deferred,
    }

    removal_count = len(spotify_remove) + len({r["video_id"] for r in yt_remove})
    if removal_count > removal_cap:
        # Leave the playlist completely alone and keep the old snapshot,
        # so the deletions aren't forgotten (and don't get re-added later).
        return {
            **plan,
            "status": "skipped_removal_cap",
            "would_remove": removal_count,
            "spotify_add": [],
            "yt_add": [],
            "spotify_remove": [],
            "yt_remove": [],
            "new_snapshot": None,
        }
    return plan


def _dedupe_pairs(pairs):
    seen = set()
    out = []
    for p in pairs:
        key = (p["spotify_track_id"], p["youtube_video_id"])
        if key not in seen:
            seen.add(key)
            out.append({"spotify_track_id": key[0], "youtube_video_id": key[1]})
    return out


def describe_plan(pair_label: str, plan: dict, names=None):
    """Readable log block for dry-run output. names: id -> "'Title' by Artist"."""
    names = names or {}

    def n(i):
        return f"{names.get(i, '?')} [{i}]"

    if plan["status"] == "skipped_removal_cap":
        return (
            f"[{pair_label}] SKIPPED: would remove {plan['would_remove']} songs "
            f"(cap {max_removals()}). Playlist left alone, snapshot kept."
        )
    lines = [f"[{pair_label}] plan ({'first sync: adds only' if plan['first_sync'] else 'sync'}):"]
    for s in plan["spotify_add"]:
        lines.append(f"  + Spotify  {n(s)}")
    for r in plan["spotify_remove"]:
        lines.append(f"  - Spotify  {n(r['track_id'])}")
    for y in plan["yt_add"]:
        lines.append(f"  + YouTube  {n(y)}")
    for r in plan["yt_remove"]:
        lines.append(f"  - YouTube  {n(r['video_id'])} (item {r['item_id']})")
    for u in plan["unmatched"]:
        lines.append(f"  ? no match for {u['platform']} '{u['title']}' by {u['artist']} [{u['source_id']}]: {u['reason']}")
    for d in plan["deferred"]:
        lines.append(f"  … deferred {d['platform']} '{d['title']}' by {d['artist']} [{d['source_id']}] (search budget)")
    lines.append(
        f"  totals: Spotify +{len(plan['spotify_add'])} -{len(plan['spotify_remove'])}, "
        f"YouTube +{len(plan['yt_add'])} -{len(plan['yt_remove'])}, "
        f"snapshot would be {len(plan['new_snapshot'])} pairs"
    )
    return "\n".join(lines)


# ============================================================
# SNAPSHOT STORAGE (conn is a psycopg2 connection from the caller)
# ============================================================

def load_snapshot(conn, pair_id):
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT spotify_track_id, youtube_video_id FROM sync_snapshot WHERE pair_id = %s",
            (pair_id,),
        )
        return [{"spotify_track_id": r[0], "youtube_video_id": r[1]} for r in cur.fetchall()]
    finally:
        cur.close()


def save_snapshot(conn, pair_id, pairs):
    """Replace the pair's snapshot in one transaction."""
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM sync_snapshot WHERE pair_id = %s", (pair_id,))
        if pairs:
            cur.executemany(
                "INSERT INTO sync_snapshot (pair_id, spotify_track_id, youtube_video_id) VALUES (%s, %s, %s)",
                [(pair_id, p["spotify_track_id"], p["youtube_video_id"]) for p in pairs],
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


# ============================================================
# SETTLE CHECK (pure)
# ============================================================

SETTLE_QUIET_RUNS = 2        # runs in a row with no new change before syncing
BACKSTOP_MINUTES = 15        # full re-check for YouTube playlists > 50 items
ERROR_BACKOFF_MINUTES = 10   # after a failed sync, wait before retrying
YT_ETAG_PAGE = 50            # the YouTube etag covers the first 50 items only

STATE_FIELDS = (
    "spotify_snapshot_id", "youtube_etag", "youtube_item_count", "pending",
    "last_change_seen_at", "quiet_runs", "youtube_checked_since_change",
    "last_checked_at", "last_synced_at", "last_error", "last_error_at",
)


def new_state():
    return {
        "spotify_snapshot_id": None, "youtube_etag": None, "youtube_item_count": None,
        "pending": True, "last_change_seen_at": None, "quiet_runs": 0,
        "youtube_checked_since_change": False, "last_checked_at": None,
        "last_synced_at": None, "last_error": None, "last_error_at": None,
    }


def settle_step(state, obs, now, check_youtube):
    """Decide what to do with one pair this run. Pure: no I/O.

    state: the pair's sync_state row as a dict, or None if never checked.
    obs:   {"spotify_snapshot_id"} plus, when check_youtube,
           {"youtube_etag", "youtube_item_count"}.
    Returns (new_state, decision, reason); decision is "sync", "wait" or "idle".

    Rules:
      * Any change (or first sight of the pair) marks it pending, resets the
        quiet counter, and does not sync yet.
      * Each run with no new change adds 1 to quiet_runs.
      * A pending pair syncs once quiet_runs >= 2 AND YouTube has been checked
        at least once since the last change (YouTube is only checked every
        other run, so an edit there could still be in progress otherwise).
      * YouTube playlists > 50 items get a full re-check every 15 min, since the
        etag only covers the first page. It still waits for 2 quiet runs.
      * After a failed sync, wait ERROR_BACKOFF_MINUTES before retrying.
    """
    first = state is None
    st = dict(state) if state else new_state()
    st["last_checked_at"] = now

    sp_changed = not first and obs["spotify_snapshot_id"] != st["spotify_snapshot_id"]
    # A YouTube etag we've never recorded (pair first seen on a Spotify-only
    # run) is a first observation, not a change.
    yt_changed = (
        check_youtube and not first
        and st["youtube_etag"] is not None
        and obs["youtube_etag"] != st["youtube_etag"]
    )
    st["spotify_snapshot_id"] = obs["spotify_snapshot_id"]
    if check_youtube:
        st["youtube_etag"] = obs["youtube_etag"]
        st["youtube_item_count"] = obs.get("youtube_item_count")

    if first or sp_changed or yt_changed:
        st.update(
            pending=True,
            last_change_seen_at=now,
            quiet_runs=0,
            youtube_checked_since_change=bool(check_youtube),
        )
        if first:
            what = "first time seen"
        else:
            what = " and ".join(n for n, c in (("Spotify", sp_changed), ("YouTube", yt_changed)) if c) + " changed"
        return st, "wait", f"{what}; waiting for {SETTLE_QUIET_RUNS} quiet runs"

    st["quiet_runs"] = (st["quiet_runs"] or 0) + 1
    if check_youtube:
        st["youtube_checked_since_change"] = True

    backstop = ""
    if (
        not st["pending"]
        and check_youtube
        and (st["youtube_item_count"] or 0) > YT_ETAG_PAGE
        and (st["last_synced_at"] is None or now - st["last_synced_at"] >= timedelta(minutes=BACKSTOP_MINUTES))
    ):
        st["pending"] = True
        backstop = f" (backstop: YouTube has {st['youtube_item_count']} items, more than the etag covers)"

    if not st["pending"]:
        return st, "idle", "no change"

    if st["last_error_at"] and now - st["last_error_at"] < timedelta(minutes=ERROR_BACKOFF_MINUTES):
        return st, "wait", f"backing off after error: {st['last_error']}"

    if st["quiet_runs"] < SETTLE_QUIET_RUNS:
        return st, "wait", f"quiet {st['quiet_runs']}/{SETTLE_QUIET_RUNS}{backstop}"
    if not st["youtube_checked_since_change"]:
        return st, "wait", "quiet long enough, but YouTube not checked since the change yet"
    return st, "sync", f"settled: {st['quiet_runs']} quiet runs{backstop}"


def after_sync(state, result, now):
    """Update state after a sync attempt (dry or real)."""
    st = dict(state)
    if result["status"] == "ok":
        st["last_synced_at"] = now
        st["last_error"] = None
        st["last_error_at"] = None
        # Songs deferred by the search budget: stay pending, continue next run.
        st["pending"] = bool(result.get("deferred"))
    elif result["status"] == "skipped_removal_cap":
        st["last_error"] = f"removal cap: would remove {result.get('would_remove')} songs"
        st["last_error_at"] = now
    else:
        st["last_error"] = (result.get("error") or "error")[:500]
        st["last_error_at"] = now
    return st


# ============================================================
# STORE (database, or a fake in tests)
# ============================================================

class DbStore:
    def __init__(self, conn):
        self.conn = conn

    def _one(self, sql, params=()):
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchone()
        finally:
            cur.close()

    def next_run_count(self):
        row = self._one("UPDATE sync_runner SET run_count = run_count + 1 WHERE id = 1 RETURNING run_count")
        self.conn.commit()
        return row[0]

    def load_pairs(self, limit, pair_id=None):
        """Keep Synced pairs linked on both platforms, least recently checked first."""
        cols = ", ".join(f"s.{f}" for f in STATE_FIELDS)
        sql = f"""SELECT p.id, p.user_id, p.playlist_name, p.spotify_playlist_id, p.youtube_playlist_id,
                         s.pair_id IS NOT NULL, {cols}
                  FROM playlists p
                  LEFT JOIN sync_state s ON s.pair_id = p.id
                  WHERE p.platform = 'both'
                    AND p.spotify_playlist_id IS NOT NULL
                    AND p.youtube_playlist_id IS NOT NULL"""
        params = []
        if pair_id:
            sql += " AND p.id = %s"
            params.append(pair_id)
        sql += " ORDER BY s.last_checked_at ASC NULLS FIRST, p.created_at LIMIT %s"
        params.append(limit)
        cur = self.conn.cursor()
        try:
            cur.execute(sql, params)
            rows = cur.fetchall()
        finally:
            cur.close()
        self.conn.rollback()
        pairs = []
        for r in rows:
            state = dict(zip(STATE_FIELDS, r[6:])) if r[5] else None
            pairs.append({"id": str(r[0]), "user_id": str(r[1]), "name": r[2],
                          "sp_id": r[3], "yt_id": r[4], "state": state})
        return pairs

    def save_state(self, pair_id, st):
        cols = ", ".join(STATE_FIELDS)
        marks = ", ".join(["%s"] * len(STATE_FIELDS))
        updates = ", ".join(f"{f} = EXCLUDED.{f}" for f in STATE_FIELDS)
        cur = self.conn.cursor()
        try:
            cur.execute(
                f"INSERT INTO sync_state (pair_id, {cols}) VALUES (%s, {marks}) "
                f"ON CONFLICT (pair_id) DO UPDATE SET {updates}",
                [pair_id] + [st[f] for f in STATE_FIELDS],
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def load_snapshot(self, pair_id):
        try:
            return load_snapshot(self.conn, pair_id)
        finally:
            self.conn.rollback()

    def load_recently_unmatched(self, pair_id, hours=24):
        cur = self.conn.cursor()
        try:
            cur.execute(
                """SELECT source_platform, source_id FROM sync_unmatched
                   WHERE pair_id = %s AND last_tried_at > now() - make_interval(hours => %s)""",
                (pair_id, hours),
            )
            return {(r[0], r[1]) for r in cur.fetchall()}
        finally:
            cur.close()
            self.conn.rollback()


# ============================================================
# PLATFORM DEPS (main.py's helpers, or a fake in tests)
# ============================================================

class MainDeps:
    """Thin wrapper over main.py's existing helpers. Imported lazily because
    main.py will import this module."""

    def __init__(self):
        import main
        import requests

        self.m = main
        self.requests = requests

    def spotify_token(self, user_id):
        return self.m.get_valid_spotify_token(user_id, get_conn=sync_db_conn)

    def youtube_token(self, user_id):
        return self.m.get_valid_youtube_token(user_id, get_conn=sync_db_conn)

    def spotify_marker(self, sp_id, token):
        r = self.requests.get(
            f"https://api.spotify.com/v1/playlists/{sp_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "snapshot_id"},
            timeout=self.m.TRACKS_TIMEOUT_SECONDS,
        )
        self.m.check_platform_response(r)
        return r.json()["snapshot_id"]

    def youtube_marker(self, yt_id, token):
        # Same request the etag test used (part=snippet, maxResults=50). 1 unit.
        r = self.requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            headers={"Authorization": f"Bearer {token}"},
            params={"part": "snippet", "playlistId": yt_id, "maxResults": YT_ETAG_PAGE},
            timeout=self.m.TRACKS_TIMEOUT_SECONDS,
        )
        self.m.check_platform_response(r)
        data = r.json()
        return data["etag"], (data.get("pageInfo") or {}).get("totalResults")

    def fetch_spotify(self, sp_id, token):
        return self.m.fetch_spotify_tracks(sp_id, token, include_ids=True)

    def fetch_youtube(self, yt_id, token):
        return self.m.fetch_youtube_tracks(yt_id, token, include_ids=True)

    def youtube_cached(self, song):
        cached = self.m.get_cached_song(
            self.m.normalize_song_text(song["title"]), self.m.normalize_song_text(song["artist"])
        )
        return bool(cached and cached.get(self.m.Platform.YOUTUBE))

    def match(self, song, target, token):
        platform = self.m.Platform.YOUTUBE if target == YOUTUBE else self.m.Platform.SPOTIFY
        return self.m.match_song(song, platform, token)

    def same_song(self, a, b):
        return bool(b.get("title") and b.get("artist")) and self.m.song_matches(a, b["title"], [b["artist"]])


# ============================================================
# RUNNER
# ============================================================

class Budget:
    def __init__(self, deadline, yt_searches, clock=time.monotonic):
        self.deadline = deadline
        self.clock = clock
        self.yt_searches_left = yt_searches
        self.yt_units = 0
        self.yt_searches = 0
        self.yt_checks = 0

    def out_of_time(self):
        return self.clock() >= self.deadline


def _youtube_list_units(result):
    if not isinstance(result, dict):
        return YT_COST_LIST  # a failed call still costs its unit
    items = len(result.get("songs", [])) + result.get("hidden", 0)
    return max(1, math.ceil(items / 50)) * YT_COST_LIST


def _label(song):
    return f"'{song.get('title')}' by {song.get('artist') or '?'}"


def _error_text(e):
    return getattr(e, "detail", None) or f"{type(e).__name__}: {e}"


def sync_pair(store, pair, deps, tokens, budget, dry_run, log):
    """Plan (and, later, apply) one pair. Returns a summary dict; never raises
    for platform errors."""
    label = f"{pair['name']} ({pair['id']})"
    if not dry_run:
        # Real writes are not implemented yet. Refuse rather than guess.
        raise RuntimeError("Real writes are not implemented yet; SYNC_DRY_RUN must be true.")
    sp_token, yt_token = tokens

    snapshot = store.load_snapshot(pair["id"])
    recently_unmatched = store.load_recently_unmatched(pair["id"])

    try:
        sp_result = deps.fetch_spotify(pair["sp_id"], sp_token)
    except Exception as e:
        sp_result = e
    try:
        yt_result = deps.fetch_youtube(pair["yt_id"], yt_token)
    except Exception as e:
        yt_result = e
    budget.yt_units += _youtube_list_units(yt_result)

    errors = [
        err
        for err in (
            validate_fetch("Spotify", sp_result, len(snapshot)),
            validate_fetch("YouTube", yt_result, len(snapshot)),
        )
        if err
    ]
    if errors:
        log(f"[{label}] ERROR: {'; '.join(errors)}. Skipped this run.")
        return {"pair": pair["id"], "status": "error", "error": "; ".join(errors)}

    sp_tracks = [
        {"track_id": s.get("track_id"), "uri": s.get("uri"), "title": s.get("title"), "artist": s.get("match_artist")}
        for s in sp_result["songs"]
    ]
    yt_tracks = [
        {"video_id": v.get("video_id"), "item_id": v.get("item_id"), "title": v.get("title"), "artist": v.get("artist")}
        for v in yt_result["songs"]
    ]
    skipped_sp = sum(1 for t in sp_tracks if not t["track_id"])

    def match_fn(song, target):
        if budget.out_of_time():
            raise MatchBudgetExceeded()
        if target == YOUTUBE:
            if not deps.youtube_cached(song):
                if budget.yt_searches_left <= 0:
                    raise MatchBudgetExceeded()
                budget.yt_searches_left -= 1
                budget.yt_searches += 1
                budget.yt_units += YT_COST_SEARCH
            return deps.match(song, YOUTUBE, yt_token)
        return deps.match(song, SPOTIFY, sp_token)

    try:
        plan = plan_sync(
            snapshot=snapshot,
            sp_tracks=sp_tracks,
            yt_tracks=yt_tracks,
            yt_unavailable=yt_result.get("unavailable", []),
            match_fn=match_fn,
            recently_unmatched=recently_unmatched,
            same_song=deps.same_song,
        )
    except Exception as e:
        # e.g. YouTubeAuthError from a search
        log(f"[{label}] ERROR while matching: {type(e).__name__}: {e}. Skipped.")
        return {"pair": pair["id"], "status": "error", "error": f"match: {type(e).__name__}"}

    # Readable names for the log.
    names = {t["track_id"]: _label(t) for t in sp_tracks if t["track_id"]}
    names.update({v["video_id"]: _label(v) for v in yt_tracks if v["video_id"]})
    for p in plan["new_snapshot"] or []:
        names.setdefault(p["youtube_video_id"], names.get(p["spotify_track_id"], "?"))
        names.setdefault(p["spotify_track_id"], names.get(p["youtube_video_id"], "?"))

    log(f"[{label}] Spotify {len(sp_tracks)} songs ({skipped_sp} local/episode, ignored); "
        f"YouTube {len(yt_tracks)} songs, {len(yt_result.get('unavailable', []))} unavailable; "
        f"snapshot {len(snapshot)} pairs; {len(recently_unmatched)} recently-unmatched skipped")
    log(describe_plan(label, plan, names))
    old = {(p["spotify_track_id"], p["youtube_video_id"]) for p in snapshot}
    for p in plan["new_snapshot"] or []:
        s, y = p["spotify_track_id"], p["youtube_video_id"]
        if (s, y) not in old:
            log(f"  = new snapshot pair: Spotify {names.get(s, '?')} [{s}] <-> YouTube {names.get(y, '?')} [{y}]")
    log(f"[{label}] DRY RUN: nothing was changed on Spotify, YouTube, or the snapshot.")

    return {
        "pair": pair["id"],
        "status": plan["status"],
        "would_remove": plan.get("would_remove"),
        "spotify_add": len(plan["spotify_add"]),
        "spotify_remove": len(plan["spotify_remove"]),
        "yt_add": len(plan["yt_add"]),
        "yt_remove": len(plan["yt_remove"]),
        "unmatched": len(plan["unmatched"]),
        "deferred": len(plan["deferred"]),
    }


def max_checks():
    return env_int("SYNC_MAX_CHECKS", 25)


def _utc_now():
    return datetime.now(timezone.utc)


def run_once(dry_run=None, pair_id=None, deps=None, store=None, log=print,
             now=None, clock=time.monotonic):
    """One pass: check every pair cheaply, sync the ones that have settled.
    No overlap lease yet (Stage 4)."""
    if dry_run is None:
        dry_run = is_dry_run()
    if not dry_run:
        raise RuntimeError("Real writes are not implemented yet; SYNC_DRY_RUN must be true.")
    now = now or _utc_now()

    if store is None:
        with sync_db_conn() as conn:
            return run_once(dry_run, pair_id, deps, DbStore(conn), log, now, clock)
    deps = deps or MainDeps()

    started = clock()
    budget = Budget(started + time_budget_seconds(), max_yt_searches(), clock)
    run_count = store.next_run_count()
    check_youtube = run_count % 2 == 0
    pairs = store.load_pairs(max_checks(), pair_id)
    log(f"auto-sync run #{run_count}: {len(pairs)} pair(s), dry_run={dry_run}, "
        f"YouTube check {'ON' if check_youtube else 'off (every other run)'}")

    results = []
    syncs = 0
    for pair in pairs:
        label = f"{pair['name']} ({pair['id']})"
        if budget.out_of_time():
            log("Time budget used up; remaining pairs carry over to the next run.")
            break
        state = pair["state"]
        try:
            tokens = (deps.spotify_token(pair["user_id"]), deps.youtube_token(pair["user_id"]))
            obs = {"spotify_snapshot_id": deps.spotify_marker(pair["sp_id"], tokens[0])}
            if check_youtube:
                budget.yt_units += YT_COST_LIST
                budget.yt_checks += 1
                obs["youtube_etag"], obs["youtube_item_count"] = deps.youtube_marker(pair["yt_id"], tokens[1])
        except Exception as e:
            # Can't even check: record it, don't touch the settle counters.
            log(f"[{label}] ERROR checking for changes: {_error_text(e)}. Skipped.")
            st = dict(state) if state else new_state()
            st.update(last_checked_at=now, last_error=f"check: {_error_text(e)}"[:500], last_error_at=now)
            store.save_state(pair["id"], st)
            results.append({"pair": pair["id"], "status": "error", "decision": "error"})
            continue

        st, decision, reason = settle_step(state, obs, now, check_youtube)
        if decision == "sync" and syncs >= max_pairs():
            decision, reason = "wait", f"settled, but this run's sync limit ({max_pairs()}) is used; next run"
        log(f"[{label}] {decision.upper()}: {reason}")

        result = {"pair": pair["id"], "status": "ok", "decision": decision}
        if decision == "sync":
            syncs += 1
            try:
                result = sync_pair(store, pair, deps, tokens, budget, dry_run, log)
            except Exception as e:
                # Last line of defence; sync_pair handles platform errors itself.
                log(f"[{label}] UNEXPECTED ERROR: {type(e).__name__}: {e}")
                result = {"pair": pair["id"], "status": "error", "error": type(e).__name__}
            result["decision"] = "sync"
            st = after_sync(st, result, now)
        store.save_state(pair["id"], st)
        results.append(result)

    elapsed = clock() - started
    log(f"auto-sync run #{run_count} done in {elapsed:.1f}s, {syncs} sync(s). "
        f"YouTube quota (est.): {budget.yt_units} units "
        f"({budget.yt_checks} etag checks, {budget.yt_searches} searches x {YT_COST_SEARCH}, list calls)")
    return {"run": run_count, "dry_run": dry_run, "check_youtube": check_youtube,
            "pairs": results, "yt_units": budget.yt_units, "seconds": round(elapsed, 1)}

