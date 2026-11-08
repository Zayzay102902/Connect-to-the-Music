import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from main import app
import psycopg2
import json
from dotenv import load_dotenv

load_dotenv()
test_db = psycopg2.connect(os.getenv("DATABASE_URL"))
client = TestClient(app)


def setup_playlist(user_id, playlist_name, platform="both"):
    cursor = test_db.cursor()
    try:
        cursor.execute(
            "INSERT INTO playlists (user_id, playlist_name, platform, songs) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (user_id, playlist_name, platform, "[]"),
        )
        test_db.commit()
    except Exception:
        test_db.rollback()
    finally:
        cursor.close()


def cleanup_playlist(user_id, playlist_name):
    cursor = test_db.cursor()
    cursor.execute(
        "DELETE FROM playlists WHERE user_id = %s AND playlist_name = %s",
        (user_id, playlist_name),
    )
    test_db.commit()
    cursor.close()


def test_create_user_duplicate():
    response = client.post(
        "/create_user", json={"username": "testuser", "password": "testpass"}
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Username already taken, please try another one."
    )


def test_login_wrong_username():
    response = client.post(
        "/login", json={"username": "nobody", "password": "testpass"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Wrong username or password."


def test_login_wrong_password():
    response = client.post(
        "/login", json={"username": "testuser", "password": "wrongpass"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Wrong username or password."


def test_google_auth_redirect():
    response = client.get("/google_auth?user_id=1", follow_redirects=False)
    assert response.status_code == 307
    assert "accounts.google.com" in response.headers["location"]


def test_spotify_auth_redirect():
    response = client.get("/spotify_auth?user_id=1", follow_redirects=False)
    assert response.status_code == 307
    assert "accounts.spotify.com" in response.headers["location"]


def test_create_playlist_already_exists():
    setup_playlist(11, "My Playlist")
    with patch("main.get_valid_youtube_token", return_value="fake_yt_token"), patch(
        "main.get_valid_spotify_token", return_value="fake_sp_token"
    ):
        response = client.post(
            "/create_playlist",
            json={"name": "My Playlist", "user_id": 11, "platform": "both"},
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Playlist already exists. Please use 'Copy Playlist' instead."
        )
    cleanup_playlist(11, "My Playlist")


def test_create_playlist_no_token():
    response = client.post(
        "/create_playlist",
        json={"name": "New Playlist", "user_id": 999, "platform": "both"},
    )
    assert response.status_code == 401
    assert (
        response.json()["detail"]
        == "No YouTube refresh token found. Please re-authenticate."
    )


def test_copy_playlist_not_found():
    with patch("main.get_valid_youtube_token", return_value="fake_yt_token"), patch(
        "main.get_valid_spotify_token", return_value="fake_sp_token"
    ):
        response = client.post(
            "/copy_playlist",
            json={
                "name": "Nonexistent Playlist",
                "platform": "youtube",
                "user_id": 11,
                "sync": False,
            },
        )
        assert response.status_code == 404
        assert (
            response.json()["detail"]
            == "Playlist not found. Please add it first using /add_playlist."
        )


def test_copy_playlist_already_on_both():
    setup_playlist(11, "My Playlist", "both")
    with patch("main.get_valid_youtube_token", return_value="fake_yt_token"), patch(
        "main.get_valid_spotify_token", return_value="fake_sp_token"
    ):
        response = client.post(
            "/copy_playlist",
            json={
                "name": "My Playlist",
                "platform": "youtube",
                "user_id": 11,
                "sync": False,
            },
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "Sorry, this playlist already exists on both platforms."
        )
    cleanup_playlist(11, "My Playlist")


def test_sync_playlist_not_found():
    with patch("main.get_valid_youtube_token", return_value="fake_yt_token"), patch(
        "main.get_valid_spotify_token", return_value="fake_sp_token"
    ):
        response = client.post(
            "/sync_playlist",
            json={
                "name": "Nonexistent Playlist",
                "user_id": 11,
                "override_platform": "youtube",
            },
        )
        assert response.status_code == 404
        assert (
            response.json()["detail"]
            == "This playlist is not synced. Please try again."
        )


def test_add_playlist_already_exists():
    setup_playlist(11, "My Playlist", "spotify")
    with patch("main.get_valid_youtube_token", return_value="fake_yt_token"), patch(
        "main.get_valid_spotify_token", return_value="fake_sp_token"
    ):
        response = client.post(
            "/add_playlist",
            json={"name": "My Playlist", "platform": "spotify", "user_id": 11},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Playlist already exists in your account."
    cleanup_playlist(11, "My Playlist")


def test_add_playlist_no_token():
    response = client.post(
        "/add_playlist",
        json={"name": "Some Playlist", "platform": "spotify", "user_id": 999},
    )
    assert response.status_code == 401
    assert (
        response.json()["detail"]
        == "No YouTube refresh token found. Please re-authenticate."
    )


def test_delete_account_not_found():
    response = client.delete("/delete_account?user_id=999")
    assert response.status_code == 404
    assert response.json()["detail"] == "User not found."


# ---------------- Token expiry uses UTC ----------------

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock
import main as main_module


def fake_db_returning(row):
    cur = MagicMock()
    cur.fetchone.return_value = row

    @contextmanager
    def fake_conn():
        conn = MagicMock()
        conn.cursor.return_value = cur
        yield conn

    return fake_conn


def test_youtube_token_refreshes_when_expired_in_utc():
    # Expired 10 minutes ago in UTC. On a machine behind UTC, comparing with
    # local time would wrongly treat this token as still valid.
    expired = main_module.utc_now() - timedelta(minutes=10)
    new_cred = MagicMock(token="new_token", expiry=main_module.utc_now() + timedelta(hours=1))
    with patch.object(main_module, "get_db_conn", fake_db_returning(("old_token", "refresh", expired))), \
         patch.object(main_module, "Credentials", return_value=new_cred):
        assert main_module.get_valid_youtube_token("u1") == "new_token"
    new_cred.refresh.assert_called_once()


def test_youtube_token_reused_when_still_valid():
    valid = main_module.utc_now() + timedelta(minutes=30)
    with patch.object(main_module, "get_db_conn", fake_db_returning(("old_token", "refresh", valid))), \
         patch.object(main_module, "Credentials") as creds:
        assert main_module.get_valid_youtube_token("u1") == "old_token"
    creds.assert_not_called()


def test_generate_playlist_stops_on_youtube_401():
    songs = [{"title": f"Song {i}", "artist": "Band"} for i in range(5)]
    sp_hit = MagicMock(status_code=200)
    yt_401 = MagicMock(status_code=401)

    def fake_get(url, **kwargs):
        if "spotify" in url:
            title = kwargs["params"]["q"].split("track:")[1].split(" artist:")[0]
            sp_hit.json.return_value = {"tracks": {"items": [{"id": "SP", "name": title, "artists": [{"name": "Band"}]}]}}
            return sp_hit
        return yt_401

    with patch.object(main_module, "get_db_conn", fake_db_returning(None)), \
         patch.object(main_module, "check_ai_limits"), \
         patch.object(main_module, "get_valid_spotify_token", return_value="sp"), \
         patch.object(main_module, "get_valid_youtube_token", return_value="yt"), \
         patch.object(main_module, "get_ai_songs", return_value=songs), \
         patch.object(main_module, "get_cached_song", return_value=None), \
         patch.object(main_module, "save_cached_song"), \
         patch.object(main_module, "create_playlist") as create, \
         patch("main.requests.get", side_effect=fake_get) as get:
        response = client.post(
            "/generate_playlist",
            json={"name": "X", "prompt": "anything", "platform": "both", "user_id": "u1"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == main_module.YOUTUBE_LOGIN_EXPIRED
    youtube_calls = [c for c in get.call_args_list if "googleapis" in c.args[0]]
    assert len(youtube_calls) == 1  # stopped after the first 401
    create.assert_not_called()


# ---------------- AI generator: matching ----------------

from main import (
    normalize_song_text,
    loose_match,
    song_matches,
    clean_ai_songs,
    is_official_channel,
    pick_youtube_result,
    parse_ai_songs,
)


def test_parse_ai_songs_valid_and_fallbacks():
    expected = [{"title": "Eye of the Tiger", "artist": "Survivor"}]
    assert parse_ai_songs('{"songs": [{"title": "Eye of the Tiger", "artist": "Survivor"}]}') == expected
    assert parse_ai_songs('[{"title": "Eye of the Tiger", "artist": "Survivor"}]') == expected
    fenced = 'Here you go:\n```json\n{"songs": [{"title": "Eye of the Tiger", "artist": "Survivor"}]}\n```'
    assert parse_ai_songs(fenced) == expected


def test_parse_ai_songs_malformed_returns_none():
    assert parse_ai_songs("") is None
    assert parse_ai_songs("Sorry, I can't help with that.") is None
    assert parse_ai_songs('{"songs": [{"title": "Eye of the Tig') is None  # cut off
    assert parse_ai_songs('{"tracks": []}') is None
    assert parse_ai_songs('{"songs": "not a list"}') is None


def yt_item(video_id, title, channel):
    return {"id": {"videoId": video_id}, "snippet": {"title": title, "channelTitle": channel}}


def test_is_official_channel():
    assert is_official_channel("Survivor - Topic", "Survivor")
    assert is_official_channel("EminemVEVO", "Eminem")
    assert is_official_channel("Eminem", "Eminem")
    assert is_official_channel("EminemMusic", "Eminem")
    assert is_official_channel("Imagine Dragons Official", "Imagine Dragons")
    assert not is_official_channel("The 4K Channel", "Eminem")
    assert not is_official_channel("Eminem Fan Club", "Eminem")


def test_pick_youtube_result_prefers_official():
    song = {"title": "Lose Yourself", "artist": "Eminem"}
    items = [
        yt_item("FAN", "Eminem - Lose Yourself (Incredible 4K Remaster 60 FPS)", "The 4K Channel"),
        yt_item("COVER", "Lose Yourself (Piano Cover)", "Piano Guy"),
        yt_item("VEVO", "Eminem - Lose Yourself [HD]", "EminemVEVO"),
    ]
    assert pick_youtube_result(song, items) == ("VEVO", None)


def test_pick_youtube_result_topic_channel():
    song = {"title": "Eye of the Tiger", "artist": "Survivor"}
    items = [
        yt_item("FAN", "Survivor - Eye of the Tiger (lyrics)", "Lyric Vibes"),
        yt_item("TOPIC", "Eye of the Tiger", "Survivor - Topic"),
    ]
    assert pick_youtube_result(song, items) == ("TOPIC", None)


def test_pick_youtube_result_falls_back_to_first_matching_upload():
    song = {"title": "Lose Yourself", "artist": "Eminem"}
    items = [
        yt_item("COVER", "Lose Yourself (Piano Cover)", "Piano Guy"),
        yt_item("FAN1", "Eminem - Lose Yourself (4K)", "The 4K Channel"),
        yt_item("FAN2", "Eminem - Lose Yourself lyrics", "Lyric Vibes"),
    ]
    assert pick_youtube_result(song, items) == ("FAN1", None)


def test_pick_youtube_result_no_match_gives_reason():
    song = {"title": "Thunder Lungs Forever", "artist": "The Imaginary Five"}
    items = [yt_item("X", "Imagine Dragons - Thunder", "ImagineDragonsVEVO")]
    video_id, reason = pick_youtube_result(song, items)
    assert video_id is None
    assert "Imagine Dragons - Thunder" in reason


def test_normalize_strips_extras():
    assert normalize_song_text("Lose Yourself (Remastered)") == "lose yourself"
    assert normalize_song_text("Don't Stop Me Now - Remastered 2011") == "dont stop me now"
    assert normalize_song_text("Eminem feat. Nobody") == "eminem"
    assert normalize_song_text("Till I Collapse [Official Video]") == "till i collapse"
    assert normalize_song_text("SurvivorVEVO") == "survivor"
    assert normalize_song_text("Rock &amp; Roll") == "rock roll"


def test_loose_match_contains_either_way():
    assert loose_match("Lose Yourself", "Lose Yourself - From 8 Mile Soundtrack")
    assert loose_match("Eye of the Tiger (Remastered)", "Eye of the Tiger")
    assert not loose_match("Go", "Gold Digger")
    assert not loose_match("", "Anything")


def test_song_matches_needs_title_and_artist():
    song = {"title": "Eye of the Tiger", "artist": "Survivor"}
    assert song_matches(song, "Eye of the Tiger", ["Survivor"])
    assert song_matches(song, "Eye Of The Tiger", ["Someone", "Survivor"])
    assert not song_matches(song, "Eye of the Tiger", ["Cover Band"])
    assert not song_matches(song, "Thunder Lungs Forever", ["Survivor"])


def test_clean_ai_songs_filters_bad_entries():
    raw = [
        {"title": "Eye of the Tiger", "artist": "Survivor"},
        {"title": "eye of the tiger (Remastered)", "artist": "survivor"},  # duplicate
        {"title": "", "artist": "Nobody"},
        {"title": "No Artist"},
        "not a dict",
        {"title": 5, "artist": "Number"},
    ] + [{"title": f"Song {i}", "artist": "Band"} for i in range(30)]
    songs = clean_ai_songs(raw)
    assert songs[0] == {"title": "Eye of the Tiger", "artist": "Survivor"}
    assert len(songs) == 20
    assert clean_ai_songs("not a list") == []
