"""Automatic two-way sync for "Keep Synced" playlists (platform = 'both').

This module has no imports from main.py, so the merge logic can be tested
without a database. Anything that talks to Spotify, YouTube, or Postgres is
passed in by the caller.

Track shapes used here:
  Spotify item:  {"track_id", "uri", "title", "artist"}
  YouTube item:  {"video_id", "item_id", "title", "artist"}   (item_id = playlistItem id)
  Snapshot pair: {"spotify_track_id", "youtube_video_id"}
"""

import os

SPOTIFY = "spotify"
YOUTUBE = "youtube"


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


def plan_sync(
    snapshot,
    sp_tracks,
    yt_tracks,
    yt_unavailable,
    match_fn,
    recently_unmatched=frozenset(),
    removal_cap=None,
):
    """Work out what to change on each side. Makes no changes itself.

    match_fn(song, target_platform) -> (id or None, reason). It may raise
    MatchBudgetExceeded to defer the song.

    recently_unmatched: set of (platform, source_id) that failed to match
    recently. They are skipped without searching.

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

    # --- 2. Songs added on Spotify -> find them on YouTube ---
    for s, track in sp_by_id.items():
        if s in snap_sp or s in paired_sp():
            continue
        if (SPOTIFY, s) in recently_unmatched:
            continue
        song = _song(track)
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
        if (YOUTUBE, y) in recently_unmatched:
            continue
        song = _song(video)
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


def describe_plan(pair_label: str, plan: dict):
    """One readable log block for dry-run output."""
    if plan["status"] == "skipped_removal_cap":
        return (
            f"[{pair_label}] SKIPPED: would remove {plan['would_remove']} songs "
            f"(cap {max_removals()}). Playlist left alone."
        )
    lines = [f"[{pair_label}] {'first sync' if plan['first_sync'] else 'sync'}:"]
    lines.append(f"  Spotify +{len(plan['spotify_add'])} -{len(plan['spotify_remove'])}  {plan['spotify_add']} {[r['track_id'] for r in plan['spotify_remove']]}")
    lines.append(f"  YouTube +{len(plan['yt_add'])} -{len(plan['yt_remove'])}  {plan['yt_add']} {[r['video_id'] for r in plan['yt_remove']]}")
    lines.append(f"  snapshot -> {len(plan['new_snapshot'])} pairs; unmatched {len(plan['unmatched'])}; deferred {len(plan['deferred'])}")
    for u in plan["unmatched"]:
        lines.append(f"    unmatched {u['platform']} {u['source_id']} '{u['title']}' by {u['artist']}: {u['reason']}")
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
