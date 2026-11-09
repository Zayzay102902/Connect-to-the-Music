"""Song matching: accents, hyphens, and collaboration uploads.
No DB, no network: main.py is imported with the connection pool stubbed,
and YouTube search responses are faked.
Run with:  pytest test/test_matching.py
"""
from unittest.mock import MagicMock, patch

import pytest

with patch("psycopg2.pool.SimpleConnectionPool"):
    import main

NIP = {"title": "Ni**as In Paris", "artist": "JAŸ-Z"}  # as Spotify sent it in the live run


def yt_item(video_id, title, channel):
    return {"id": {"videoId": video_id}, "snippet": {"title": title, "channelTitle": channel}}


OFFICIAL_COLLAB_VEVO = yt_item(
    "gG_dA32oH44", "Jay-Z &amp; Kanye West - Ni**as In Paris (Explicit)", "KanyeWestVEVO"
)


def candidates(song, item):
    parsed = main.parse_youtube_title(item["snippet"]["title"].replace("&amp;", "&"), item["snippet"]["channelTitle"])
    return parsed["title"], [parsed["artist"], item["snippet"]["channelTitle"]]


# ---------------- the exact live failure ----------------

def test_live_case_match_song_finds_the_official_collab_video():
    response = MagicMock(status_code=200)
    response.json.return_value = {"items": [OFFICIAL_COLLAB_VEVO]}
    with patch.object(main, "get_cached_song", return_value=None), \
         patch.object(main, "save_cached_song") as saved, \
         patch.object(main.requests, "get", return_value=response):
        video_id, reason = main.match_song(NIP, main.Platform.YOUTUBE, "token")
    assert (video_id, reason) == ("gG_dA32oH44", None)
    saved.assert_called_once()


def test_live_case_song_matches():
    title, artists = candidates(NIP, OFFICIAL_COLLAB_VEVO)
    assert main.song_matches(NIP, title, artists)


# ---------------- accents and hyphens ----------------

@pytest.mark.parametrize("a,b", [
    ("JAŸ-Z", "Jay-Z"),
    ("JAŸ-Z", "JAY Z"),
    ("Jay-Z", "JAY Z"),
    ("Beyoncé", "Beyonce"),
    ("Sigur Rós", "Sigur Ros"),
])
def test_accents_and_hyphens_compare_equal(a, b):
    assert main.loose_match(a, b)
    assert main.loose_match(b, a)


def test_official_channel_check_ignores_accents():
    assert main.is_official_channel("Beyoncé", "Beyonce")
    assert main.is_official_channel("BeyonceVEVO", "Beyoncé")


def test_cache_keys_are_unchanged():
    # normalize_song_text builds song_cache keys; it must not fold accents,
    # or existing cache rows would stop being found.
    assert main.normalize_song_text("JAŸ-Z") == "jaÿ z"
    assert main.normalize_song_text("Beyoncé") == "beyoncé"


# ---------------- collaborations ----------------

def test_collab_on_non_vevo_co_artist_channel_beats_fan_upload_listed_first():
    song = {"title": "Ni**as In Paris", "artist": "JAŸ-Z"}
    fan = yt_item("fan", "JAY-Z - Ni**as In Paris (Lyrics)", "Lyrics Hub")
    official = yt_item("official", "Jay-Z & Kanye West - Ni**as In Paris (Explicit)", "Kanye West")
    assert main.pick_youtube_result(song, [fan, official]) == ("official", None)


def test_collab_with_artists_in_the_other_order_still_matches():
    song = {"title": "Ni**as In Paris", "artist": "JAŸ-Z"}
    item = yt_item("v1", "Kanye West & Jay-Z - Ni**as In Paris", "Kanye West")
    assert main.pick_youtube_result(song, [item]) == ("v1", None)


def test_credited_artists_splits_common_separators():
    assert main.credited_artists("Jay-Z & Kanye West") == ["Jay-Z", "Kanye West"]
    assert main.credited_artists("A, B and C") == ["A", "B", "C"]
    assert main.credited_artists("Drake x Future") == ["Drake", "Future"]
    assert main.credited_artists("Calvin Harris feat. Rihanna") == ["Calvin Harris", "Rihanna"]


def test_collab_rule_needs_our_artist_among_the_credits():
    # Kanye's channel, credits Kanye only: not "official" for a Jay-Z song.
    assert not main.is_collab_official("Kanye West", "Jay-Z", "Kanye West")
    assert not main.is_collab_official("Kanye West", "Jay-Z", "Kanye West & Pusha T")
    assert main.is_collab_official("Kanye West", "JAŸ-Z", "Jay-Z & Kanye West")


# ---------------- still rejects wrong songs ----------------

def test_rejects_different_song_from_the_same_collab_channel():
    song = {"title": "Ni**as In Paris", "artist": "JAŸ-Z"}
    otis = yt_item("otis", "Jay-Z & Kanye West - Otis (Explicit)", "KanyeWestVEVO")
    video_id, reason = main.pick_youtube_result(song, [otis])
    assert video_id is None and "didn't match" in reason


def test_rejects_video_credited_only_to_the_co_artist():
    song = {"title": "Ni**as In Paris", "artist": "JAŸ-Z"}
    item = yt_item("k", "Kanye West - Ni**as In Paris", "Kanye West")
    assert main.pick_youtube_result(song, [item])[0] is None


def test_rejects_cover_by_an_unrelated_artist():
    song = {"title": "Ni**as In Paris", "artist": "JAŸ-Z"}
    item = yt_item("cover", "Some Band - Ni**as In Paris (Cover)", "Some Band")
    assert main.pick_youtube_result(song, [item])[0] is None


def test_rejects_similar_artist_name():
    assert not main.loose_match("Jay-Z", "Jay Rock")
    song = {"title": "Ni**as In Paris", "artist": "Jay-Z"}
    item = yt_item("jr", "Jay Rock - Ni**as In Paris", "Jay Rock")
    assert main.pick_youtube_result(song, [item])[0] is None
