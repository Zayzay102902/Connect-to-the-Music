"""Real-write path (SYNC_DRY_RUN=false) against fake platforms. No DB, no network.
Run with:  pytest test/test_writes.py
Runs are 2 minutes apart; a new pair syncs on run 3."""
from datetime import timedelta

import autosync
from autosync_fakes import FakeWorld, Sim


def pairs_of(sim, pair_id="pair-1"):
    return {(p["spotify_track_id"], p["youtube_video_id"]) for p in sim.store.snapshots.get(pair_id, [])}


def run_until_sync(sim, max_runs=6):
    for _ in range(max_runs):
        r = sim.run(dry_run=False)
        if r["pairs"][0]["decision"] == "sync":
            return r
    raise AssertionError("never synced")


def sp_ids(world):
    return sorted(s[0] for s in world.sp_songs)


def yt_ids(world):
    return sorted(v[0] for v in world.yt_songs)


def test_first_real_sync_adds_both_ways_and_saves_snapshot():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist"), ("ytC", "Song C", "Artist")])
    sim = Sim(world=w)
    r = run_until_sync(sim)
    assert r["pairs"][0]["applied"] is True
    assert sp_ids(w) == ["spA", "spB", "spC"]
    assert yt_ids(w) == ["ytA", "ytB", "ytC"]
    assert pairs_of(sim) == {("spA", "ytA"), ("spB", "ytB"), ("spC", "ytC")}
    assert not [x for x in w.writes if "remove" in x[0]]


def test_own_writes_do_not_look_like_a_change():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist"), ("ytC", "Song C", "Artist")])
    sim = Sim(world=w)
    run_until_sync(sim)
    st = sim.state()
    assert st["spotify_snapshot_id"] == w.sp_snapshot   # from the write response
    assert st["youtube_etag"] == w.yt_etag              # re-read after writes
    decisions = [sim.decision(sim.run(dry_run=False)) for _ in range(6)]
    assert decisions == ["idle"] * 6
    assert w.calls["sp_fetch"] == 1                     # no extra syncs


def test_youtube_lag_after_write_is_waited_out_so_no_false_change():
    # Real behaviour seen on dev: right after an insert, the list still shows the old contents.
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist")])
    w.yt_lag_reads = 2
    sim = Sim(world=w)
    run_until_sync(sim)
    assert w.slept == [2, 3]                          # caught up on the 3rd re-read
    assert sim.state()["youtube_etag"] == w.yt_etag   # the post-write etag, not the stale one
    assert sim.state()["youtube_item_count"] == 2
    assert [sim.decision(sim.run(dry_run=False)) for _ in range(4)] == ["idle"] * 4


def test_youtube_lag_longer_than_retries_costs_one_noop_sync_at_most():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist")])
    w.yt_lag_reads = 99
    sim = Sim(world=w)
    run_until_sync(sim)
    w.yt_lag_reads = 0
    writes_before = len(w.writes)
    decisions = [sim.decision(sim.run(dry_run=False)) for _ in range(6)]
    assert decisions.count("sync") == 1 and len(w.writes) == writes_before   # one no-op sync, no writes
    assert decisions[-1] == "idle"


def test_spotify_stale_snapshot_right_after_a_write_is_ignored():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist")])
    sim = Sim(world=w)
    run_until_sync(sim)
    w.sp_lag = True        # next GET returns the pre-write snapshot_id
    assert sim.decision(sim.run(dry_run=False)) == "idle"
    assert sim.state()["spotify_snapshot_id"] == w.sp_snapshot
    assert [sim.decision(sim.run(dry_run=False)) for _ in range(4)] == ["idle"] * 4


def test_real_user_edit_inside_the_stale_window_is_delayed_not_lost():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist")], yt_songs=[("ytA", "Song A", "Artist")])
    sim = Sim(world=w)
    run_until_sync(sim)                                  # run 3 at 12:04
    w.sp_songs.append(("spD", "Song D", "Artist")); w.edit_spotify("user-edit")
    d = [sim.decision(sim.run(dry_run=False)) for _ in range(5)]
    assert d[0] == "idle"          # 12:06: within 3 min of the sync, ignored for now
    assert d[1] == "wait"          # 12:08: seen as a change
    assert "sync" in d
    assert "ytD" in yt_ids(w)


def test_removal_on_youtube_removes_from_spotify_and_updates_snapshot():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist"), ("ytB", "Song B", "Artist")])
    sim = Sim(world=w)
    run_until_sync(sim)
    for _ in range(2):
        sim.run(dry_run=False)                               # get past the stale window
    w.yt_songs = [v for v in w.yt_songs if v[0] != "ytB"]; w.edit_youtube("user-removed-B")
    run_until_sync(sim)
    assert sp_ids(w) == ["spA"]
    assert ("spotify_remove", ["spotify:track:spB"]) in w.writes
    assert pairs_of(sim) == {("spA", "ytA")}


def test_removal_cap_means_no_writes_at_all():
    songs = [(f"sp{i}", f"Song {i}", "Artist") for i in range(12)]
    w = FakeWorld(sp_songs=list(songs), yt_songs=[("yt" + s[0][2:], s[1], s[2]) for s in songs])
    sim = Sim(world=w)
    sim.store.snapshots["pair-1"] = [{"spotify_track_id": s[0], "youtube_video_id": "yt" + s[0][2:]} for s in songs]
    w.sp_songs = songs[:1]                                   # 11 removed on Spotify
    r = run_until_sync(sim)
    assert r["pairs"][0]["status"] == "skipped_removal_cap"
    assert w.writes == []
    assert len(sim.store.snapshots["pair-1"]) == 12          # old snapshot kept


def test_first_sync_never_removes_even_if_called_directly():
    plan = {"first_sync": True, "spotify_add": [], "yt_add": [], "spotify_remove": [{"track_id": "x", "uri": "spotify:track:x"}],
            "yt_remove": [], "new_snapshot": []}
    import pytest
    with pytest.raises(autosync.WriteAborted):
        autosync.apply_plan({"name": "p", "id": "1", "sp_id": "S", "yt_id": "Y"}, plan, [], ("t", "t"),
                            None, autosync.Budget(1e9, 0, lambda: 0.0, yt_writes=10), lambda *_: None)


def test_hard_write_failure_saves_no_snapshot_and_next_sync_does_not_duplicate():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist"), ("ytC", "Song C", "Artist")])
    sim = Sim(world=w)
    w.fail_write = "yt_add"           # Spotify add (C) succeeds, YouTube add (B) fails
    r = run_until_sync(sim)
    assert r["pairs"][0]["status"] == "error"
    assert "pair-1" not in sim.store.snapshots                # nothing saved
    assert sp_ids(w) == ["spA", "spB", "spC"]                 # C already landed
    w.fail_write = None
    for _ in range(8):                                        # back off, then retry
        sim.run(dry_run=False)
    assert sp_ids(w) == ["spA", "spB", "spC"]                 # C NOT added twice
    assert yt_ids(w) == ["ytA", "ytB", "ytC"]
    assert pairs_of(sim) == {("spA", "ytA"), ("spB", "ytB"), ("spC", "ytC")}


def test_video_youtube_refuses_is_skipped_and_remembered():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist")])
    w.refuse_videos = {"ytB"}
    sim = Sim(world=w)
    r = run_until_sync(sim)
    assert r["pairs"][0]["status"] == "ok"
    assert pairs_of(sim) == {("spA", "ytA")}                  # B left out of the snapshot
    assert ("spotify", "spB") in sim.store.unmatched          # not retried for 24h


def test_youtube_write_cap_defers_the_rest_to_the_next_run(monkeypatch):
    monkeypatch.setenv("SYNC_MAX_YT_WRITES", "2")
    monkeypatch.setenv("SYNC_MAX_YT_SEARCHES", "10")
    songs = [(f"sp{k}", f"Song {k}", "Artist") for k in "ABCDE"]
    w = FakeWorld(sp_songs=list(songs), yt_songs=[])
    sim = Sim(world=w)
    r = run_until_sync(sim)
    assert len([x for x in w.writes if x[0] == "yt_add"]) == 2
    assert len(sim.store.snapshots["pair-1"]) == 2            # only what landed
    assert sim.state()["pending"] is True                     # keeps going
    for _ in range(3):
        sim.run(dry_run=False)
    assert yt_ids(w) == ["ytA", "ytB", "ytC", "ytD", "ytE"]
    assert len([x for x in w.writes if x[0] == "yt_add"]) == 5   # each added exactly once


def test_spotify_writes_are_batched_at_100():
    w = FakeWorld(sp_songs=[], yt_songs=[(f"yt{i}", f"Song {i}", "Artist") for i in range(150)])
    sim = Sim(world=w)
    run_until_sync(sim)
    adds = [x for x in w.writes if x[0] == "spotify_add"]
    assert [len(a[1]) for a in adds] == [100, 50]


def test_dry_run_makes_no_writes():
    w = FakeWorld(sp_songs=[("spA", "Song A", "Artist"), ("spB", "Song B", "Artist")],
                  yt_songs=[("ytA", "Song A", "Artist")])
    sim = Sim(world=w)
    for _ in range(4):
        sim.run(dry_run=True)
    assert w.writes == []
    assert "pair-1" not in sim.store.snapshots
