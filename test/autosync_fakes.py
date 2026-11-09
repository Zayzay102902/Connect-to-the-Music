"""In-memory stand-ins for the database and the Spotify/YouTube helpers, so
autosync.run_once can be exercised over many fake runs with no network or DB."""
from datetime import datetime, timedelta, timezone

import autosync

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
RUN_INTERVAL = timedelta(minutes=2)


class FakeStore:
    def __init__(self, pairs):
        self.run_count = 0
        self.pairs = pairs  # list of {"id","user_id","name","sp_id","yt_id"}
        self.states = {}
        self.snapshots = {}
        self.unmatched = set()

    lease = None          # run_id holding the lease, or None
    released = []         # summaries passed to release_lease

    def acquire_lease(self, run_id):
        if self.lease is not None:
            return None
        self.lease = run_id
        self.run_count += 1
        return self.run_count

    def release_lease(self, run_id, summary):
        if self.lease == run_id:
            self.lease = None
        self.released = self.released + [summary]

    def load_pairs(self, limit, pair_id=None):
        rows = [dict(p, state=self.states.get(p["id"])) for p in self.pairs if not pair_id or p["id"] == pair_id]
        rows.sort(key=lambda r: (r["state"] or {}).get("last_checked_at") or datetime.min.replace(tzinfo=timezone.utc))
        return rows[:limit]

    def save_state(self, pair_id, st):
        assert set(st) == set(autosync.STATE_FIELDS), set(st) ^ set(autosync.STATE_FIELDS)
        self.states[pair_id] = dict(st)

    def load_snapshot(self, pair_id):
        return list(self.snapshots.get(pair_id, []))

    def load_recently_unmatched(self, pair_id, hours=24):
        return set(self.unmatched)


class FakeWorld:
    """What the two platforms currently look like. Tests mutate this between runs."""

    def __init__(self, sp_songs=None, yt_songs=None, yt_count=None):
        self.sp_snapshot = "sp-v1"
        self.yt_etag = "yt-v1"
        self.yt_count = yt_count
        self.sp_songs = sp_songs or [("spA", "Song A", "Artist")]
        self.yt_songs = yt_songs or [("ytA", "Song A", "Artist")]
        self.fail_fetch = None   # "spotify" / "youtube" to make the full fetch fail
        self.fail_marker = None  # exception to raise from the cheap checks
        self.calls = {"sp_marker": 0, "yt_marker": 0, "sp_fetch": 0, "yt_fetch": 0, "search": 0}

    def edit_spotify(self, new_version):
        self.sp_snapshot = new_version

    def edit_youtube(self, new_version):
        self.yt_etag = new_version


class FakeDeps:
    def __init__(self, world):
        self.w = world

    def spotify_token(self, user_id):
        return "sp-token"

    def youtube_token(self, user_id):
        return "yt-token"

    def spotify_marker(self, sp_id, token):
        self.w.calls["sp_marker"] += 1
        if self.w.fail_marker:
            raise self.w.fail_marker
        return self.w.sp_snapshot

    def youtube_marker(self, yt_id, token):
        self.w.calls["yt_marker"] += 1
        if self.w.fail_marker:
            raise self.w.fail_marker
        return self.w.yt_etag, self.w.yt_count if self.w.yt_count is not None else len(self.w.yt_songs)

    def fetch_spotify(self, sp_id, token):
        self.w.calls["sp_fetch"] += 1
        if self.w.fail_fetch == "spotify":
            raise RuntimeError("HTTP 503")
        return {"songs": [{"title": t, "artist": a, "track_id": i, "uri": f"spotify:track:{i}", "match_artist": a}
                          for i, t, a in self.w.sp_songs], "hidden": 0, "truncated": False}

    def fetch_youtube(self, yt_id, token):
        self.w.calls["yt_fetch"] += 1
        if self.w.fail_fetch == "youtube":
            raise RuntimeError("HTTP 503")
        return {"songs": [{"title": t, "artist": a, "video_id": i, "item_id": f"item-{i}"}
                          for i, t, a in self.w.yt_songs], "hidden": 0, "truncated": False, "unavailable": []}

    def youtube_cached(self, song):
        return False

    def match(self, song, target, token):
        self.w.calls["search"] += 1
        key = song["title"].split()[-1]  # "Song B" -> "B"
        return (f"sp{key}" if target == autosync.SPOTIFY else f"yt{key}"), None

    def same_song(self, a, b):
        return autosync.default_same_song(a, b)


PAIR = {"id": "pair-1", "user_id": "u1", "name": "Road Trip", "sp_id": "SP1", "yt_id": "YT1"}


class Sim:
    """Drives run_once at 2-minute intervals."""

    def __init__(self, world=None, pairs=(PAIR,), log=None):
        self.world = world or FakeWorld()
        self.store = FakeStore([dict(p) for p in pairs])
        self.deps = FakeDeps(self.world)
        self.now = T0
        self.lines = []
        self.log = log or self.lines.append

    def run(self):
        result = autosync.run_once(
            dry_run=True, deps=self.deps, store=self.store, log=self.log,
            now=self.now, clock=lambda: 0.0,
        )
        self.now += RUN_INTERVAL
        return result

    def decision(self, result, pair_id="pair-1"):
        return next(p["decision"] for p in result["pairs"] if p["pair"] == pair_id)

    def state(self, pair_id="pair-1"):
        return self.store.states[pair_id]
