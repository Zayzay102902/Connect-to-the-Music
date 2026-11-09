"""Stage 3 tests: settle check over many fake runs. No DB, no network.
Run with:  pytest test/test_settle.py
Runs are 2 minutes apart; run #1 is odd, so YouTube is checked on runs 2, 4, 6...
"""
from datetime import timedelta

import autosync
from autosync import settle_step
from autosync_fakes import FakeWorld, Sim, T0


def decisions(sim, n):
    return [sim.decision(sim.run()) for _ in range(n)]


# ---------------- the main flow ----------------

def test_new_pair_syncs_after_two_quiet_runs_then_goes_idle():
    sim = Sim()
    # run1: first seen (YouTube not checked: odd run)
    # run2: quiet 1, YouTube checked (first etag recorded, not a "change")
    # run3: quiet 2 -> sync
    # run4+: idle
    assert decisions(sim, 5) == ["wait", "wait", "sync", "idle", "idle"]
    assert sim.world.calls["sp_fetch"] == 1 and sim.world.calls["yt_fetch"] == 1
    assert sim.state()["pending"] is False


def test_youtube_checked_every_other_run_spotify_every_run():
    sim = Sim()
    decisions(sim, 6)
    assert sim.world.calls["sp_marker"] == 6
    assert sim.world.calls["yt_marker"] == 3


def test_change_waits_for_two_quiet_runs():
    sim = Sim()
    decisions(sim, 4)                       # settled and idle (runs 1-4)
    sim.world.edit_spotify("sp-v2")
    assert decisions(sim, 4) == ["wait", "wait", "sync", "idle"]   # runs 5-8


def test_continuing_edits_keep_postponing_the_sync():
    sim = Sim()
    decisions(sim, 4)
    seq = []
    for version in ("sp-v2", "sp-v3", "sp-v4"):     # user still editing: runs 5, 6, 7
        sim.world.edit_spotify(version)
        seq.append(sim.decision(sim.run()))
    seq += decisions(sim, 3)                         # runs 8, 9: quiet; 9 syncs; 10 idle
    assert seq == ["wait", "wait", "wait", "wait", "sync", "idle"]
    assert sim.world.calls["sp_fetch"] == 2          # initial sync + one after edits


def test_youtube_change_is_only_seen_on_youtube_runs():
    sim = Sim()
    decisions(sim, 4)                       # runs 1-4
    sim.world.edit_youtube("yt-v2")         # happens before run 5 (odd: not checked)
    r5 = sim.decision(sim.run())
    r6 = sim.decision(sim.run())            # even: change seen here
    assert (r5, r6) == ("idle", "wait")
    assert sim.state()["last_change_seen_at"] == T0 + timedelta(minutes=10)
    assert decisions(sim, 2) == ["wait", "sync"]   # runs 7 (quiet 1), 8 (quiet 2, YT checked)


def test_spotify_change_on_odd_run_needs_a_youtube_check_before_sync():
    sim = Sim()
    decisions(sim, 4)
    sim.world.edit_spotify("sp-v2")                 # seen on run 5 (odd, no YT check)
    assert sim.decision(sim.run()) == "wait"
    assert sim.state()["youtube_checked_since_change"] is False
    assert sim.decision(sim.run()) == "wait"        # run 6: quiet 1, YT checked
    assert sim.state()["youtube_checked_since_change"] is True
    assert sim.decision(sim.run()) == "sync"        # run 7: quiet 2


def test_youtube_edit_right_after_spotify_edit_resets_the_wait():
    sim = Sim()
    decisions(sim, 4)
    sim.world.edit_spotify("sp-v2")
    assert sim.decision(sim.run()) == "wait"        # run 5: Spotify change
    sim.world.edit_youtube("yt-v2")
    assert sim.decision(sim.run()) == "wait"        # run 6: YouTube change, counter reset
    assert sim.state()["quiet_runs"] == 0
    assert decisions(sim, 2) == ["wait", "sync"]    # runs 7, 8


# ---------------- errors ----------------

def test_failed_fetch_keeps_pending_and_backs_off_then_retries():
    sim = Sim()
    decisions(sim, 2)
    sim.world.fail_fetch = "youtube"
    r = sim.run()                                    # run 3: settled, sync attempted, fetch fails
    assert sim.decision(r) == "sync" and r["pairs"][0]["status"] == "error"
    assert sim.state()["pending"] is True
    assert "YouTube fetch failed" in sim.state()["last_error"]
    sim.world.fail_fetch = None
    # Runs 4-7 are within 10 minutes of the error: wait. Run 8 (10 min later) retries.
    assert decisions(sim, 5) == ["wait", "wait", "wait", "wait", "sync"]
    assert sim.state()["last_error"] is None and sim.state()["pending"] is False


def test_check_failure_is_recorded_and_other_pairs_still_run():
    world = FakeWorld()
    pairs = (
        {"id": "pair-1", "user_id": "u1", "name": "A", "sp_id": "S1", "yt_id": "Y1"},
        {"id": "pair-2", "user_id": "u1", "name": "B", "sp_id": "S2", "yt_id": "Y2"},
    )
    sim = Sim(world=world, pairs=pairs)

    calls = {"n": 0}
    real_marker = sim.deps.spotify_marker

    def flaky_marker(sp_id, token):
        calls["n"] += 1
        if sp_id == "S1":
            raise RuntimeError("HTTP 500")
        return real_marker(sp_id, token)

    sim.deps.spotify_marker = flaky_marker
    r = sim.run()
    assert sim.decision(r, "pair-1") == "error"
    assert sim.decision(r, "pair-2") == "wait"
    assert "HTTP 500" in sim.store.states["pair-1"]["last_error"]


def test_removal_cap_is_treated_as_an_error_and_not_synced_repeatedly():
    world = FakeWorld(
        sp_songs=[("spA", "Song A", "Artist")],
        yt_songs=[("ytA", "Song A", "Artist")] + [(f"yt{i}", f"Song {i}", "Artist") for i in range(11)],
    )
    sim = Sim(world=world)
    sim.store.snapshots["pair-1"] = [{"spotify_track_id": f"sp{i}", "youtube_video_id": f"yt{i}"} for i in range(11)] + [
        {"spotify_track_id": "spA", "youtube_video_id": "ytA"}
    ]
    r = [sim.run() for _ in range(3)]
    assert r[2]["pairs"][0]["status"] == "skipped_removal_cap"
    assert "removal cap" in sim.state()["last_error"]
    assert sim.state()["pending"] is True
    assert decisions(sim, 2) == ["wait", "wait"]     # backing off, not hammering


# ---------------- limits / backstop ----------------

def test_sync_limit_per_run_carries_over():
    pairs = tuple({"id": f"pair-{i}", "user_id": "u1", "name": f"P{i}", "sp_id": f"S{i}", "yt_id": f"Y{i}"} for i in range(3))
    sim = Sim(pairs=pairs)
    import os
    os.environ["SYNC_MAX_PAIRS"] = "2"
    try:
        sim.run(); sim.run()
        r3 = sim.run()
        synced = [p for p in r3["pairs"] if p["decision"] == "sync"]
        assert len(synced) == 2
        r4 = sim.run()
        assert [p["pair"] for p in r4["pairs"] if p["decision"] == "sync"] == ["pair-2"]
    finally:
        del os.environ["SYNC_MAX_PAIRS"]


def test_big_youtube_playlist_gets_a_backstop_recheck_every_15_minutes():
    sim = Sim(world=FakeWorld(yt_count=120))
    seq = decisions(sim, 12)            # runs 1-12, 24 minutes, nothing changes
    syncs = [i + 1 for i, d in enumerate(seq) if d == "sync"]
    # Run n happens at 12:00 + 2(n-1) min. Initial sync: run 3 (12:04).
    # Backstop due at 12:19; run 10 (12:18) is too early, run 12 (12:22) is
    # the first YouTube-check run after it. Nothing has changed for many runs,
    # so the quiet requirement is already met and it re-syncs right away.
    assert syncs == [3, 12]


def test_small_playlist_has_no_backstop():
    sim = Sim()
    seq = decisions(sim, 20)
    assert seq.count("sync") == 1


# ---------------- settle_step directly ----------------

def test_first_seen_on_spotify_only_run_does_not_count_youtube_as_change_later():
    st, d, _ = settle_step(None, {"spotify_snapshot_id": "s1"}, T0, check_youtube=False)
    assert d == "wait" and st["youtube_etag"] is None
    st, d, reason = settle_step(st, {"spotify_snapshot_id": "s1", "youtube_etag": "e1", "youtube_item_count": 3},
                                T0 + timedelta(minutes=2), check_youtube=True)
    assert d == "wait" and st["quiet_runs"] == 1 and "quiet 1/2" in reason


def test_dry_run_still_required():
    import pytest
    with pytest.raises(RuntimeError):
        autosync.run_once(dry_run=False, store=object(), deps=object())
