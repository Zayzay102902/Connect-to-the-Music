"""Stage 1 tests: merge/diff logic with fake data. No DB, no network.
Run with:  pytest test/test_autosync.py
(This file does not import main.py, so it doesn't need DATABASE_URL.)
"""
import pytest

import autosync
from autosync import (
    SPOTIFY,
    YOUTUBE,
    MatchBudgetExceeded,
    plan_sync,
    validate_fetch,
)

# A fake "catalog": which Spotify track and YouTube video each song maps to.
CATALOG = {
    ("Song A", "Artist"): ("spA", "ytA"),
    ("Song B", "Artist"): ("spB", "ytB"),
    ("Song C", "Artist"): ("spC", "ytC"),
    ("Song D", "Artist"): ("spD", "ytD"),
}


def sp(track_id, title, artist="Artist"):
    return {"track_id": track_id, "uri": f"spotify:track:{track_id}", "title": title, "artist": artist}


def yt(video_id, title, artist="Artist", item_id=None):
    return {"video_id": video_id, "item_id": item_id or f"item-{video_id}", "title": title, "artist": artist}


def pair(s, y):
    return {"spotify_track_id": s, "youtube_video_id": y}


class FakeMatcher:
    def __init__(self, catalog=CATALOG, budget=None):
        self.catalog = catalog
        self.calls = []
        self.budget = budget

    def __call__(self, song, target):
        if self.budget is not None and len(self.calls) >= self.budget:
            raise MatchBudgetExceeded()
        self.calls.append((song["title"], target))
        ids = self.catalog.get((song["title"], song["artist"]))
        if not ids:
            return None, "No results"
        return (ids[0] if target == SPOTIFY else ids[1]), None


def snapshot_set(plan):
    return {(p["spotify_track_id"], p["youtube_video_id"]) for p in plan["new_snapshot"]}


# ---------------- first sync ----------------

def test_first_sync_adds_both_ways_and_never_removes():
    plan = plan_sync(
        snapshot=[],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[yt("ytB", "Song B"), yt("ytC", "Song C")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["first_sync"] is True
    assert plan["yt_add"] == ["ytA"]
    assert plan["spotify_add"] == ["spC"]
    assert plan["spotify_remove"] == [] and plan["yt_remove"] == []
    assert snapshot_set(plan) == {("spA", "ytA"), ("spB", "ytB"), ("spC", "ytC")}


def test_first_sync_unmatched_song_is_left_out_of_snapshot():
    plan = plan_sync(
        snapshot=[],
        sp_tracks=[sp("spA", "Song A"), sp("spX", "Obscure Song")],
        yt_tracks=[],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["yt_add"] == ["ytA"]
    assert snapshot_set(plan) == {("spA", "ytA")}
    assert [u["source_id"] for u in plan["unmatched"]] == ["spX"]


# ---------------- steady state ----------------

def test_nothing_changed_means_no_actions_and_no_searches():
    matcher = FakeMatcher()
    plan = plan_sync(
        snapshot=[pair("spA", "ytA"), pair("spB", "ytB")],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[yt("ytA", "Song A"), yt("ytB", "Song B")],
        yt_unavailable=set(),
        match_fn=matcher,
        removal_cap=10,
    )
    assert not plan["spotify_add"] and not plan["yt_add"]
    assert not plan["spotify_remove"] and not plan["yt_remove"]
    assert matcher.calls == []
    assert snapshot_set(plan) == {("spA", "ytA"), ("spB", "ytB")}


def test_removed_on_spotify_is_removed_on_youtube():
    plan = plan_sync(
        snapshot=[pair("spA", "ytA"), pair("spB", "ytB")],
        sp_tracks=[sp("spA", "Song A")],
        yt_tracks=[yt("ytA", "Song A"), yt("ytB", "Song B")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["yt_remove"] == [{"video_id": "ytB", "item_id": "item-ytB"}]
    assert plan["spotify_remove"] == []
    assert snapshot_set(plan) == {("spA", "ytA")}


def test_removed_on_youtube_is_removed_on_spotify():
    plan = plan_sync(
        snapshot=[pair("spA", "ytA"), pair("spB", "ytB")],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[yt("ytA", "Song A")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["spotify_remove"] == [{"track_id": "spB", "uri": "spotify:track:spB"}]
    assert plan["yt_remove"] == []
    assert snapshot_set(plan) == {("spA", "ytA")}


def test_added_on_each_side_is_copied_to_the_other():
    plan = plan_sync(
        snapshot=[pair("spA", "ytA")],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[yt("ytA", "Song A"), yt("ytC", "Song C")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["yt_add"] == ["ytB"]
    assert plan["spotify_add"] == ["spC"]
    assert snapshot_set(plan) == {("spA", "ytA"), ("spB", "ytB"), ("spC", "ytC")}


def test_same_song_added_on_both_sides_is_paired_not_duplicated():
    plan = plan_sync(
        snapshot=[pair("spA", "ytA")],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[yt("ytA", "Song A"), yt("ytB", "Song B")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["yt_add"] == [] and plan["spotify_add"] == []
    assert snapshot_set(plan) == {("spA", "ytA"), ("spB", "ytB")}


def test_removed_on_both_sides_just_drops_the_pair():
    plan = plan_sync(
        snapshot=[pair("spA", "ytA"), pair("spB", "ytB")],
        sp_tracks=[sp("spA", "Song A")],
        yt_tracks=[yt("ytA", "Song A")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert not plan["spotify_remove"] and not plan["yt_remove"]
    assert snapshot_set(plan) == {("spA", "ytA")}


def test_duplicate_videos_are_all_removed():
    plan = plan_sync(
        snapshot=[pair("spA", "ytA"), pair("spB", "ytB")],
        sp_tracks=[sp("spA", "Song A")],
        yt_tracks=[yt("ytA", "Song A"), yt("ytB", "Song B", item_id="i1"), yt("ytB", "Song B", item_id="i2")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert sorted(r["item_id"] for r in plan["yt_remove"]) == ["i1", "i2"]


# ---------------- safety ----------------

def test_removal_cap_leaves_playlist_alone_and_keeps_old_snapshot():
    snapshot = [pair(f"sp{i}", f"yt{i}") for i in range(12)]
    plan = plan_sync(
        snapshot=snapshot,
        sp_tracks=[sp("sp0", "Song 0")],  # 11 removed on Spotify
        yt_tracks=[yt(f"yt{i}", f"Song {i}") for i in range(12)],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["status"] == "skipped_removal_cap"
    assert plan["would_remove"] == 11
    assert not plan["yt_remove"] and not plan["spotify_remove"]
    assert not plan["yt_add"] and not plan["spotify_add"]
    assert plan["new_snapshot"] is None  # caller must keep the old one


def test_removals_at_exactly_the_cap_go_through():
    snapshot = [pair(f"sp{i}", f"yt{i}") for i in range(11)]
    plan = plan_sync(
        snapshot=snapshot,
        sp_tracks=[sp("sp0", "Song 0")],  # exactly 10 removed
        yt_tracks=[yt(f"yt{i}", f"Song {i}") for i in range(11)],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["status"] == "ok"
    assert len(plan["yt_remove"]) == 10


def test_unavailable_video_is_not_treated_as_removed():
    # ytB went private: it's not in the song list, only in yt_unavailable.
    plan = plan_sync(
        snapshot=[pair("spA", "ytA"), pair("spB", "ytB")],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[yt("ytA", "Song A")],
        yt_unavailable={"ytB"},
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["spotify_remove"] == []
    assert ("spB", "ytB") in snapshot_set(plan)


def test_manual_sync_swapping_video_does_not_delete_spotify_track():
    # /sync_playlist replaced ytA with ytA2 (another upload of Song A).
    catalog = {("Song A", "Artist"): ("spA", "ytA2")}
    plan = plan_sync(
        snapshot=[pair("spA", "ytA")],
        sp_tracks=[sp("spA", "Song A")],
        yt_tracks=[yt("ytA2", "Song A")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(catalog),
        removal_cap=10,
    )
    assert plan["spotify_remove"] == []
    assert plan["spotify_add"] == []
    assert snapshot_set(plan) == {("spA", "ytA2")}


def test_spotify_version_swap_does_not_delete_video():
    # User replaced spA with spA_remaster; both map to ytA.
    catalog = {("Song A (Remaster)", "Artist"): ("spA_remaster", "ytA")}
    plan = plan_sync(
        snapshot=[pair("spA", "ytA")],
        sp_tracks=[sp("spA_remaster", "Song A (Remaster)")],
        yt_tracks=[yt("ytA", "Song A")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(catalog),
        removal_cap=10,
    )
    assert plan["yt_remove"] == []
    assert plan["yt_add"] == []
    assert snapshot_set(plan) == {("spA_remaster", "ytA")}


def test_video_still_used_by_another_pair_is_not_removed():
    plan = plan_sync(
        snapshot=[pair("spA", "ytA"), pair("spA_live", "ytA")],
        sp_tracks=[sp("spA", "Song A")],  # spA_live removed
        yt_tracks=[yt("ytA", "Song A")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["yt_remove"] == []


def test_recently_unmatched_songs_are_not_searched_again():
    matcher = FakeMatcher()
    plan = plan_sync(
        snapshot=[],
        sp_tracks=[sp("spX", "Obscure Song")],
        yt_tracks=[],
        yt_unavailable=set(),
        match_fn=matcher,
        recently_unmatched={(SPOTIFY, "spX")},
        removal_cap=10,
    )
    assert matcher.calls == []
    assert plan["unmatched"] == [] and plan["new_snapshot"] == []


def test_budget_exceeded_defers_without_marking_unmatched():
    plan = plan_sync(
        snapshot=[],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[],
        yt_unavailable=set(),
        match_fn=FakeMatcher(budget=1),
        removal_cap=10,
    )
    assert plan["yt_add"] == ["ytA"]
    assert [d["source_id"] for d in plan["deferred"]] == ["spB"]
    assert plan["unmatched"] == []
    assert snapshot_set(plan) == {("spA", "ytA")}


def test_youtube_video_without_artist_is_unmatched_not_searched():
    matcher = FakeMatcher()
    plan = plan_sync(
        snapshot=[],
        sp_tracks=[],
        yt_tracks=[yt("ytZ", "some vlog", artist=None)],
        yt_unavailable=set(),
        match_fn=matcher,
        removal_cap=10,
    )
    assert matcher.calls == []
    assert plan["unmatched"][0]["source_id"] == "ytZ"


def test_deferred_song_is_retried_next_run_and_not_removed():
    # Run 1 deferred spB. Run 2 the snapshot doesn't have it, so it's
    # still "added", not "removed".
    plan = plan_sync(
        snapshot=[pair("spA", "ytA")],
        sp_tracks=[sp("spA", "Song A"), sp("spB", "Song B")],
        yt_tracks=[yt("ytA", "Song A")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["yt_add"] == ["ytB"]
    assert plan["spotify_remove"] == [] and plan["yt_remove"] == []


# ---------------- local matching (no duplicate uploads) ----------------

def test_song_already_on_other_side_as_different_upload_is_paired_not_added():
    # Real case from the dev dry run: search picks ytA_search, but the
    # playlist already has ytA_existing for the same song.
    catalog = {("Song A", "Artist"): ("spA", "ytA_search")}
    matcher = FakeMatcher(catalog)
    plan = plan_sync(
        snapshot=[],
        sp_tracks=[sp("spA", "Song A")],
        yt_tracks=[yt("ytA_existing", "song a")],
        yt_unavailable=set(),
        match_fn=matcher,
        removal_cap=10,
    )
    assert plan["yt_add"] == [] and plan["spotify_add"] == []
    assert snapshot_set(plan) == {("spA", "ytA_existing")}
    assert matcher.calls == []  # no search spent


def test_local_match_never_steals_an_already_paired_video():
    # ytA is paired with spA. A new Spotify copy of the same song must not
    # be paired with ytA a second time through local matching.
    catalog = {("Song A", "Artist"): ("spA2", "ytA")}
    plan = plan_sync(
        snapshot=[pair("spA", "ytA")],
        sp_tracks=[sp("spA", "Song A"), sp("spA2", "Song A")],
        yt_tracks=[yt("ytA", "Song A")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(catalog),
        removal_cap=10,
    )
    # Falls through to search, which says ytA; ytA is already there, so no add.
    assert plan["yt_add"] == []
    assert snapshot_set(plan) == {("spA", "ytA"), ("spA2", "ytA")}


def test_manual_sync_swap_is_resolved_locally_without_search():
    matcher = FakeMatcher({})
    plan = plan_sync(
        snapshot=[pair("spA", "ytA")],
        sp_tracks=[sp("spA", "Song A")],
        yt_tracks=[yt("ytA2", "Song A")],
        yt_unavailable=set(),
        match_fn=matcher,
        removal_cap=10,
    )
    assert plan["spotify_remove"] == [] and plan["spotify_add"] == []
    assert snapshot_set(plan) == {("spA", "ytA2")}
    assert matcher.calls == []


def test_different_song_is_not_local_matched():
    plan = plan_sync(
        snapshot=[],
        sp_tracks=[sp("spA", "Song A")],
        yt_tracks=[yt("ytB", "Song B")],
        yt_unavailable=set(),
        match_fn=FakeMatcher(),
        removal_cap=10,
    )
    assert plan["yt_add"] == ["ytA"] and plan["spotify_add"] == ["spB"]


# ---------------- fetch validation ----------------

def ok(songs, truncated=False):
    return {"songs": songs, "hidden": 0, "truncated": truncated}


def test_validate_rejects_exception():
    assert "failed" in validate_fetch("Spotify", RuntimeError("boom"), 5)


def test_validate_rejects_truncated():
    assert "longer than" in validate_fetch("YouTube", ok([{}], truncated=True), 0)


def test_validate_rejects_empty_when_snapshot_has_songs():
    assert "no songs" in validate_fetch("Spotify", ok([]), 3)


def test_validate_allows_empty_on_first_sync():
    assert validate_fetch("Spotify", ok([]), 0) is None


def test_validate_rejects_bad_shape():
    assert validate_fetch("Spotify", {"nope": 1}, 0) is not None


# ---------------- config ----------------

@pytest.mark.parametrize("value,expected", [
    (None, True), ("", True), ("true", True), ("TRUE", True), ("yes", True),
    ("false", False), ("0", False), ("off", False), ("No", False),
])
def test_dry_run_defaults_to_true(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("SYNC_DRY_RUN", raising=False)
    else:
        monkeypatch.setenv("SYNC_DRY_RUN", value)
    assert autosync.is_dry_run() is expected
