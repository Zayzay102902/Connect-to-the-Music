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

    def save_snapshot(self, pair_id, pairs):
        self.snapshots[pair_id] = [dict(p) for p in pairs]

    def record_unmatched(self, pair_id, rows):
        for r in rows:
            self.unmatched.add((r["platform"], r["source_id"]))


class FakeWorld:
    """What the two platforms currently look like. Tests mutate this between runs."""

    def __init__(self, sp_songs=None, yt_songs=None, yt_count=None):
        self.sp_snapshot = "sp-v1"
        self.yt_etag = "yt-v1"
        self.yt_count = yt_count
        self.sp_songs = list(sp_songs) if sp_songs is not None else [("spA", "Song A", "Artist")]
        self.yt_songs = list(yt_songs) if yt_songs is not None else [("ytA", "Song A", "Artist")]
        self.fail_fetch = None   # "spotify" / "youtube" to make the full fetch fail
        self.fail_marker = None  # exception to raise from the cheap checks
        self.fail_write = None   # "spotify_add" / "yt_add" to make that write fail hard
        self.refuse_videos = set()  # videos YouTube won't accept (soft failure)
        self.sp_version = 0
        self.stale_sp_snapshot = None
        self.sp_lag = False      # True: Spotify GET returns the pre-write snapshot_id once
        self.yt_lag_reads = 0    # re-reads after a write that still return the old list
        self.stale_yt = None     # (etag, songs) before our first YouTube write this sync
        self.slept = []
        self.writes = []
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
        if self.w.sp_lag and self.w.stale_sp_snapshot:
            self.w.sp_lag = False
            return self.w.stale_sp_snapshot
        return self.w.sp_snapshot

    def youtube_marker(self, yt_id, token):
        self.w.calls["yt_marker"] += 1
        if self.w.fail_marker:
            raise self.w.fail_marker
        return self.w.yt_etag, self.w.yt_count if self.w.yt_count is not None else len(self.w.yt_songs)

    def youtube_marker_full(self, yt_id, token):
        self.w.calls["yt_marker"] += 1
        if self.w.yt_lag_reads > 0 and self.w.stale_yt is not None:
            self.w.yt_lag_reads -= 1
            etag, songs = self.w.stale_yt
        else:
            etag, songs = self.w.yt_etag, self.w.yt_songs
        return {"etag": etag, "count": len(songs),
                "video_ids": [v[0] for v in songs], "item_ids": [f"item-{v[0]}" for v in songs]}

    def sleep(self, seconds):
        self.w.slept.append(seconds)

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

    # ---- writes: mutate the fake world like the real APIs would ----

    def _song_for(self, some_id):
        key = some_id[2:]  # "spB" / "ytB" -> "B"
        return f"Song {key}", "Artist"

    def _bump_spotify(self):
        self.w.sp_version += 1
        self.w.stale_sp_snapshot = self.w.sp_snapshot   # GET may lag (see world.sp_lag)
        self.w.sp_snapshot = f"sp-w{self.w.sp_version}"
        return self.w.sp_snapshot

    def spotify_add(self, sp_id, token, uris):
        assert len(uris) <= autosync.SPOTIFY_BATCH
        self.w.writes.append(("spotify_add", list(uris)))
        if self.w.fail_write == "spotify_add":
            raise RuntimeError("HTTP 502")
        for u in uris:
            tid = u.rsplit(":", 1)[1]
            self.w.sp_songs.append((tid, *self._song_for(tid)))
        return self._bump_spotify()

    def spotify_remove(self, sp_id, token, uris):
        assert len(uris) <= autosync.SPOTIFY_BATCH
        self.w.writes.append(("spotify_remove", list(uris)))
        ids = {u.rsplit(":", 1)[1] for u in uris}
        self.w.sp_songs = [s for s in self.w.sp_songs if s[0] not in ids]  # every copy
        return self._bump_spotify()

    def youtube_add(self, yt_id, token, video_id):
        if self.w.stale_yt is None:
            self.w.stale_yt = (self.w.yt_etag, list(self.w.yt_songs))
        self.w.writes.append(("yt_add", video_id))
        if video_id in self.w.refuse_videos:
            raise autosync.SoftWriteError("YouTube refused the video (HTTP 404 videoNotFound)")
        if self.w.fail_write == "yt_add":
            raise RuntimeError("HTTP 500")
        self.w.yt_songs.append((video_id, *self._song_for(video_id)))
        self.w.yt_etag = f"yt-w{len(self.w.writes)}"
        return f"item-{video_id}"

    def youtube_remove(self, token, item_id):
        if self.w.stale_yt is None:
            self.w.stale_yt = (self.w.yt_etag, list(self.w.yt_songs))
        self.w.writes.append(("yt_remove", item_id))
        self.w.yt_songs = [v for v in self.w.yt_songs if f"item-{v[0]}" != item_id]
        self.w.yt_etag = f"yt-w{len(self.w.writes)}"


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

    def run(self, dry_run=True):
        result = autosync.run_once(
            dry_run=dry_run, deps=self.deps, store=self.store, log=self.log,
            now=self.now, clock=lambda: 0.0,
        )
        self.now += RUN_INTERVAL
        return result

    def decision(self, result, pair_id="pair-1"):
        return next(p["decision"] for p in result["pairs"] if p["pair"] == pair_id)

    def state(self, pair_id="pair-1"):
        return self.store.states[pair_id]
