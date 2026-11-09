# 🎶 Connect to the Music 🎶

A full-stack web application that allows users to create, sync, copy, and manage playlists across both **YouTube** and **Spotify** from a single unified dashboard.

- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL
- **Frontend:** Vanilla HTML, CSS, and JavaScript

---

## Table of Contents

1. [Features](#features)
2. [Tech Stack](#tech-stack)
3. [Prerequisites](#prerequisites)
4. [Environment Variables](#environment-variables)
5. [Database Setup](#database-setup)
6. [Google Cloud Console Setup](#google-cloud-console-setup)
7. [Spotify Developer Setup](#spotify-developer-setup)
8. [Running the App](#running-the-app)
9. [Running the Tests](#running-the-tests)
10. [How to Use the App](#how-to-use-the-app)
    - [Signing In](#signing-in)
    - [The Actions Menu](#the-actions-menu)
    - [Viewing a Playlist's Songs](#viewing-a-playlists-songs)
    - [Create Playlist](#create-playlist)
    - [Add Playlist](#add-playlist)
    - [Copy Playlist](#copy-playlist)
    - [Sync Playlist](#sync-playlist)
    - [Delete Playlist](#delete-playlist)
    - [Generate with AI](#generate-with-ai)
    - [Logout](#logout)
    - [Delete Account](#delete-account)
11. [Automatic Syncing (Keep Synced)](#automatic-syncing-keep-synced)
12. [API Endpoints Reference](#api-endpoints-reference)
13. [Notes and Limitations](#notes-and-limitations)

---

## Features

- **Sign in with Google** — One click to sign in. The first time, you're also sent to Spotify to connect your Spotify account.
- **Actions Menu** — All playlist and account actions live in one **Actions** dropdown in the navbar (keyboard friendly: arrow keys move, Escape closes).
- **View a Playlist's Songs** — Click any playlist card to see its songs on Spotify and/or YouTube, side by side, read live from each platform.
- **Create Playlists** — Create a new empty playlist on YouTube, Spotify, or both platforms simultaneously from the dashboard.
- **Add an Existing Playlist** — Import a playlist that already exists on YouTube or Spotify into the app's database so it can be managed alongside your other playlists.
- **Copy a Playlist** — Copy a playlist from one platform to the other. The app searches for each song on the target platform and recreates the playlist there. Tick **Keep Synced?** to keep both copies in sync automatically from then on.
- **Sync Playlists (manual)** — For playlists that live on both platforms, pick one as the source of truth and overwrite the other platform's version with its songs.
- **Automatic Syncing** — Playlists marked Keep Synced are checked every 2 minutes. Songs added or removed on either platform are copied to the other one, with safety limits so a glitch can never wipe a playlist. See [Automatic Syncing](#automatic-syncing-keep-synced).
- **Delete a Playlist** — Delete a playlist from its platform(s) and remove it from the app.
- **Generate with AI** — Describe the music you want (e.g. "pumped up workout music") and Claude suggests about 20 real songs. Each song is searched and verified on Spotify and/or YouTube before it's added; songs that can't be found are skipped and listed with the reason.
- **Logout** — Securely log out of your session. Clears your OAuth access tokens from the database and returns you to the sign-in page.
- **Delete Your Account** — Permanently remove your account and all associated playlists from the database with a single confirmation.

---

## Tech Stack

| Layer      | Technology                                                            |
|------------|-----------------------------------------------------------------------|
| Language   | Python 3.x                                                            |
| Framework  | FastAPI (served with uvicorn)                                         |
| DB Driver  | psycopg2                                                              |
| Database   | PostgreSQL (the hosted version uses Neon)                             |
| Auth       | Google OAuth2 (sign-in + YouTube), Spotify OAuth2                     |
| APIs       | Google YouTube Data API v3, Spotify Web API, Anthropic Claude API     |
| Frontend   | Vanilla HTML, CSS, JavaScript                                         |
| Hosting    | Render (web service) + cron-job.org (calls the auto-sync endpoint)    |
| Other      | python-dotenv, google-auth, google-auth-oauthlib, requests, anthropic |

---

## Prerequisites

Before running this project, make sure you have the following installed and configured:

- **Python 3.x** — [https://www.python.org/downloads/](https://www.python.org/downloads/)
- **PostgreSQL** — [https://www.postgresql.org/download/](https://www.postgresql.org/download/) (or a hosted Postgres such as Neon)
- **A Google Cloud Console account** with a project that has the YouTube Data API v3 enabled and OAuth 2.0 credentials configured (see [Google Cloud Console Setup](#google-cloud-console-setup))
- **A Spotify Developer account** with an app created in the Spotify Developer Dashboard (see [Spotify Developer Setup](#spotify-developer-setup))
- **An Anthropic API key** — only needed for Generate with AI

### Python Dependencies

Install all required packages with:

```bash
pip install -r requirements.txt
```

To run the tests you also need `pytest`:

```bash
pip install pytest
```

---

## Environment Variables

Create a `.env` file in the root of the project directory with the following variables:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/database_name

GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET_KEY=your_google_client_secret

GOOGLE_REDIRECT_URL=http://127.0.0.1:8000/google_auth/callback
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/google_auth/callback

SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8000/api/spotify/callback

ANTHROPIC_API_KEY=your_anthropic_api_key

# Only needed if you use automatic syncing
SYNC_SECRET=a_long_random_string

# Optional (defaults shown)
APP_URL=http://127.0.0.1:8000
AI_DAILY_LIMIT=5
AI_GLOBAL_DAILY_LIMIT=100
SYNC_DRY_RUN=true
SYNC_MAX_REMOVALS=10
SYNC_MAX_PAIRS=5
SYNC_MAX_CHECKS=25
SYNC_TIME_BUDGET_SECONDS=20
SYNC_MAX_YT_SEARCHES=5
SYNC_MAX_YT_WRITES=10
```

| Variable                   | Description                                                                                         |
|----------------------------|-----------------------------------------------------------------------------------------------------|
| `DATABASE_URL`             | PostgreSQL connection string. Replace `username`, `password`, and `database_name` with your values. |
| `GOOGLE_CLIENT_ID`         | The OAuth 2.0 Client ID from your Google Cloud Console project.                                     |
| `GOOGLE_CLIENT_SECRET_KEY` | The OAuth 2.0 Client Secret from your Google Cloud Console project.                                 |
| `GOOGLE_REDIRECT_URL`      | The redirect URI registered in Google Cloud Console. Locally: `http://127.0.0.1:8000/google_auth/callback`. |
| `GOOGLE_REDIRECT_URI`      | Same as above — both variables are used in different parts of the backend.                          |
| `SPOTIFY_CLIENT_ID`        | The Client ID from your app in the Spotify Developer Dashboard.                                     |
| `SPOTIFY_CLIENT_SECRET`    | The Client Secret from your app in the Spotify Developer Dashboard.                                 |
| `SPOTIFY_REDIRECT_URI`     | The redirect URI registered in Spotify. Locally: `http://127.0.0.1:8000/api/spotify/callback`.      |
| `ANTHROPIC_API_KEY`        | Claude API key for Generate with AI. Server-side only — never sent to the browser. On Render, set it under Environment. |
| `APP_URL`                  | Optional. Where the app sends you after sign-in. Default `http://127.0.0.1:8000`. Set it to your public URL when hosted. |
| `AI_DAILY_LIMIT`           | Optional. AI generations per user per day. Default `5`.                                             |
| `AI_GLOBAL_DAILY_LIMIT`    | Optional. AI generations across all users per day. Default `100`. Caps daily API spend.             |
| `SYNC_SECRET`              | Required for automatic syncing. The value callers must send in the `X-Sync-Secret` header. If it's not set, the sync endpoint rejects every call. |
| `SYNC_DRY_RUN`             | Optional. Default `true`: auto-sync only logs what it would change. Set to `false` to make real changes. |
| `SYNC_MAX_REMOVALS`        | Optional. Default `10`. If more songs than this would be removed from one pair in one run, nothing is changed for that pair. |
| `SYNC_MAX_PAIRS`           | Optional. Default `5`. Most playlist pairs synced in one run; the rest wait for the next run.       |
| `SYNC_MAX_CHECKS`          | Optional. Default `25`. Most playlist pairs checked for changes in one run.                         |
| `SYNC_TIME_BUDGET_SECONDS` | Optional. Default `20`. A run stops starting new work after this many seconds.                      |
| `SYNC_MAX_YT_SEARCHES`     | Optional. Default `5`. Most YouTube searches per run (100 quota units each).                        |
| `SYNC_MAX_YT_WRITES`       | Optional. Default `10`. Most YouTube adds + removals per run (50 quota units each).                 |

> **Windows tip:** `python-dotenv` does not override variables that are already set in your system environment. If your system has its own `DATABASE_URL`, the app uses that one instead of the one in `.env`. (The auto-sync code reads `DATABASE_URL` straight from `.env` when the file exists, so it isn't affected.)

---

## Database Setup

1. Open **pgAdmin** (or any PostgreSQL query tool) and create a new database. You can name it anything — just make sure the name matches what you put in `DATABASE_URL`.

2. Open the query tool for your new database and run the following SQL **all at once**. You can copy and paste the entire block and execute it with no modifications:

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE platform_enum AS ENUM ('youtube', 'spotify', 'both');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_id TEXT UNIQUE NOT NULL,
    youtube_refresh_token TEXT,
    youtube_access_token TEXT,
    youtube_token_expiry TIMESTAMP,
    spotify_refresh_token TEXT,
    spotify_access_token TEXT,
    spotify_token_expiry TIMESTAMP
);

CREATE TABLE playlists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    playlist_name TEXT,
    platform platform_enum,
    songs JSONB,
    youtube_playlist_id TEXT,
    spotify_playlist_id TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, playlist_name)
);

-- Generate with AI: one row per billed Claude call (daily limits + token usage)
CREATE TABLE ai_generations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    prompt TEXT,
    input_tokens INT,
    output_tokens INT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX ai_generations_user_day_idx ON ai_generations (user_id, created_at);
CREATE INDEX ai_generations_day_idx ON ai_generations (created_at);

-- Generate with AI and auto-sync: cache of verified matches (saves YouTube quota)
CREATE TABLE song_cache (
    title_key TEXT NOT NULL,
    artist_key TEXT NOT NULL,
    spotify_track_id TEXT,
    youtube_video_id TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (title_key, artist_key)
);
```

3. **Automatic syncing tables.** Run the SQL in [`autosync_tables.sql`](autosync_tables.sql). It creates four tables, all safe to re-run (`IF NOT EXISTS`):

| Table            | What it's for                                                                                                  |
|------------------|----------------------------------------------------------------------------------------------------------------|
| `sync_snapshot`  | One row per matched song per Keep Synced playlist: the Spotify track and YouTube video both sides agreed on after the last sync. Comparing against it is how the app tells "added" from "removed". |
| `sync_state`     | One row per Keep Synced playlist: the last change markers seen on each platform, whether a change is waiting to be synced, and the last error. |
| `sync_unmatched` | Songs that couldn't be found on the other platform, so they aren't searched again (and don't spend quota) for 24 hours. |
| `sync_runner`    | A single row used as a lock so two sync runs never overlap, plus a run counter.                               |

> **Important:** The `pgcrypto` extension must be enabled first — it provides `gen_random_uuid()` used to generate UUID primary keys. The `platform_enum` type must be created before the tables. The tables use UUIDs as primary keys rather than auto-incrementing integers, which prevents sequential ID enumeration. All the sync tables are deleted automatically along with their playlist (`ON DELETE CASCADE`).

---

## Google Cloud Console Setup

1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/) and sign in.
2. Click **Select a project** at the top, then click **New Project**. Give it a name and click **Create**.
3. In the left sidebar, go to **APIs & Services > Library**.
4. Search for **YouTube Data API v3** and click **Enable**.
5. In the left sidebar, go to **APIs & Services > Credentials**.
6. Click **Create Credentials > OAuth 2.0 Client IDs**.
7. If prompted, configure the **OAuth consent screen** first:
   - Choose **External** as the user type.
   - Fill in the required fields (App name, support email, developer email).
   - You do not need to add any scopes manually at this step — click through and save.
8. Back on the **Create OAuth Client ID** screen:
   - Set the **Application type** to **Web application**.
   - Under **Authorized redirect URIs**, click **Add URI** and enter: `http://127.0.0.1:8000/google_auth/callback`
   - Click **Create**.
9. Copy the **Client ID** and **Client Secret** into your `.env` file as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET_KEY`.

> **Note:** When testing the app, Google will display a warning screen saying the app is not verified. This is expected for apps still in development. Click **"Continue"** (or "Advanced > Go to [app name]") to proceed — you are the developer, so this warning does not apply to you.

> **YouTube quota:** The YouTube Data API has a daily quota (10,000 units by default). A search costs 100 units, adding or removing a video costs 50, and reading a page of a playlist costs 1. Generate with AI and automatic syncing both use this quota.

---

## Spotify Developer Setup

1. Go to [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in with your Spotify account.
2. Click **Create App**.
3. Fill in the app name and description (anything works for local development).
4. Under **Redirect URIs**, add: `http://127.0.0.1:8000/api/spotify/callback`
5. Accept the terms and click **Save**.
6. From your app's dashboard page, copy the **Client ID** and **Client Secret** into your `.env` file as `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`.

> **Development Mode Limit:** Spotify restricts apps in development mode to **5 users total**, including yourself. If you need more than 5 users, you must request a quota extension through the Spotify Developer Dashboard.

> **API Change (February 2026):** Spotify updated their playlist API in February 2026. This app already accounts for those changes — it uses the updated `/playlists/{id}/items` endpoint instead of the deprecated `/tracks` endpoint.

---

## Running the App

1. Make sure PostgreSQL is running and your database is set up (see [Database Setup](#database-setup)).
2. Make sure your `.env` file is in the root project directory and correctly filled out.
3. Open a terminal in the root project directory and run:

```bash
uvicorn main:app --reload
```

4. Once the server is running, open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser. The backend serves the frontend itself, so there's no separate step for `index.html`.

> **Important:** Use `http://127.0.0.1:8000` (not `localhost`) so the URL matches the redirect URIs registered with Google and Spotify.

---

## Running the Tests

These test files need **no database and no network** (the platforms and the database are faked):

```bash
pytest test/test_autosync.py test/test_settle.py test/test_writes.py test/test_matching.py
```

| File                     | What it covers                                                                  |
|--------------------------|---------------------------------------------------------------------------------|
| `test/test_autosync.py`  | The add/remove comparison and merge logic, and the fetch safety checks.          |
| `test/test_settle.py`    | The "wait until edits stop" check over many simulated runs, and the run lock.    |
| `test/test_writes.py`    | Real-write mode against fake platforms: adds, removals, caps, failures, lag.     |
| `test/test_matching.py`  | Song matching: accents ("JAŸ-Z" = "Jay-Z") and collaboration uploads.            |

> **`test/test_main.py` is out of date.** It connects to the database in `DATABASE_URL` at import time and writes test rows there, and some of its tests call `/create_user` and `/login`, which no longer exist. Don't point it at a production database.

---

## How to Use the App

### Signing In

1. Open the app and click **"Continue with Google"**.
2. Sign in with your Google account and grant permission to manage your YouTube playlists.
3. **First time only:** you're then sent to **Spotify** — log in and grant permission to manage your Spotify playlists.
4. You land on your dashboard. There's no separate account to create; your Google account is your account.

Access tokens are refreshed automatically in the background. If a refresh ever fails, the app shows a "login has expired" message — log out and sign in again.

---

### The Actions Menu

Every action below is in the **Actions** dropdown in the navbar: Create, Add, Copy, Sync, Delete Playlist, Generate with AI, then (in red) Delete Account and Logout. Arrow keys move through the menu, Escape closes it, and clicking outside closes it.

---

### Viewing a Playlist's Songs

**What it does:** Shows the songs currently in a playlist, read live from Spotify and/or YouTube.

**How to use it:**
- Click a playlist card (or focus it and press Enter).
- A window lists the songs for each platform the playlist is on, each in its own section, so a problem on one platform doesn't hide the other.
- Deleted or private YouTube videos aren't listed; the window says how many were hidden.
- Up to 1,000 songs per platform are shown.

**Backend endpoint:** `GET /playlist_tracks`

---

### Create Playlist

**What it does:** Creates a new empty playlist and saves it to the database.

**How to use it:**
- Open **Actions > Create Playlist**.
- Enter a playlist name.
- Select a platform: **Both** (default), **YouTube**, or **Spotify**.
  - Selecting **Both** creates the playlist on YouTube and Spotify at the same time, and marks it **Keep Synced** (see [Automatic Syncing](#automatic-syncing-keep-synced)).
  - Selecting a single platform only creates it there.
- Click **"Create"**.

The playlist will appear on your dashboard once created.

**Backend endpoint:** `POST /create_playlist`

---

### Add Playlist

**What it does:** Imports a playlist that already exists on YouTube or Spotify into the app's database so it can be managed from the dashboard.

**How to use it:**
- Open **Actions > Add Playlist**.
- Enter the playlist name **exactly as it appears on the platform** — spelling and capitalization must match exactly.
- Select the platform the playlist lives on (**YouTube** or **Spotify**).
- Click **"Add"**.

The app will find the playlist on the selected platform, pull its songs, save everything to the database, and display the playlist on your dashboard.

**Backend endpoint:** `POST /add_playlist`

---

### Copy Playlist

**What it does:** Copies a playlist from one platform to the other. The app searches for each song on the target platform and adds them to a newly created playlist there.

**How to use it:**
- Open **Actions > Copy Playlist**.
- Enter the playlist name **exactly as it appears in the database**.
- Select the platform the playlist currently lives on (**YouTube** or **Spotify**) — the app will copy it to the other platform.
- Optionally check **"Keep Synced?"** — the playlist is then tracked on both platforms and kept in sync automatically (see [Automatic Syncing](#automatic-syncing-keep-synced)). You can also still use Sync Playlist on it.
- Click **"Copy"**.

**Backend endpoint:** `POST /copy_playlist`

---

### Sync Playlist

**What it does:** For playlists that exist on both platforms, this overwrites one platform's version with the other. One platform is designated the "source of truth" and its songs completely replace whatever is on the other platform. (This is the manual, one-way sync. Two-way syncing happens automatically — see [Automatic Syncing](#automatic-syncing-keep-synced).)

**How to use it:**
- Open **Actions > Sync Playlist**.
- Enter the playlist name exactly as it appears in the database.
- Select the **Source of Truth Platform** — whichever platform you pick, its current songs will be pushed to the other platform, replacing everything there.
  - For example: selecting **YouTube** will push all songs from the YouTube playlist into Spotify, overwriting the Spotify version.
- Click **"Sync"**.

> This feature only works on playlists whose platform is set to **"both"** in the database (i.e., playlists that exist on both platforms).

**Backend endpoint:** `POST /sync_playlist`

---

### Delete Playlist

**What it does:** Deletes a playlist from its platform(s) and removes it from the database.

**How to use it:**
- Open **Actions > Delete Playlist**.
- Enter the playlist name exactly as it appears in the database.
- Select the platform:
  - **Both** — finds the playlist whatever platform it's on, deletes it from every platform it's on, and removes it from the database.
  - **YouTube** or **Spotify** — only finds playlists that live on just that platform; deletes it there and removes it from the database. A Keep Synced (both) playlist can't be deleted from just one side — choose **Both**.
- Click **"Delete"**.

> On Spotify, "deleting" means unfollowing the playlist, which removes it from your library.

**Backend endpoint:** `DELETE /delete_playlist`

---

### Generate with AI

**What it does:** Builds a new playlist from a short description using Claude (`claude-haiku-5-5`).

**How to use it:**
- Open **Actions > Generate with AI**.
- Enter a playlist name and describe the music (up to 300 characters).
- Pick **Both** (default), **Spotify**, or **YouTube**. **Both** turns on Keep Synced and only adds songs found on both platforms.
- Click **Generate**. It can take up to a minute. When it finishes you'll see "Added X of Y songs" plus any skipped songs and why. The button is disabled while a request is running, so double-clicking can't create two playlists.

**How it works:** Claude returns up to 20 songs as JSON. Each song is checked against the song cache, then searched on the platform. The top results must match the title and artist loosely (case, accents, hyphens, "feat.", "(Remastered)" and similar extras are ignored), and on YouTube official uploads (VEVO, "- Topic", the artist's own channel, or a co-artist's official channel when the video credits both artists) are preferred. Songs that don't match are skipped. Each user gets `AI_DAILY_LIMIT` generations per day, and there's an overall `AI_GLOBAL_DAILY_LIMIT`; both are checked before Claude is called. Every Claude call's token usage is logged and stored. If your YouTube login has expired, the generator stops at the first rejection and tells you, instead of failing song by song.

**Backend endpoint:** `POST /generate_playlist`

---

### Logout

**What it does:** Ends your current session securely. Clears your YouTube and Spotify access tokens from the database (refresh tokens are preserved so signing back in is smooth), removes your session from the browser, and returns you to the sign-in page.

**How to use it:**
- Open **Actions > Logout** (styled in red).
- A confirmation window will appear asking "Are you sure you want to log out?"
- Click **"Logout"** to confirm, or **"Cancel"** to close it and stay on the dashboard.

> To sign back in, click **"Continue with Google"** again. Because your Spotify refresh token is kept, you normally won't be sent through Spotify again.

**Backend endpoint:** `POST /logout`

---

### Delete Account

**What it does:** Permanently deletes your user account and all your playlists from the database.

**How to use it:**
- Open **Actions > Delete Account** (styled in red).
- A confirmation window will appear. Confirm to proceed.

> **This action cannot be undone.** All playlists associated with your account (and their sync records and AI usage records) are also deleted from the database, thanks to `ON DELETE CASCADE`. The playlists themselves on Spotify and YouTube are not deleted.

**Backend endpoint:** `DELETE /delete_account`

---

## Automatic Syncing (Keep Synced)

Playlists marked **Keep Synced** (stored as `platform = 'both'`) are kept in sync both ways: add or remove a song on Spotify and the same change is made on YouTube, and the other way round.

### How it works

1. **Something calls the sync endpoint every 2 minutes.** The app has no timer of its own. An external scheduler (cron-job.org) sends `POST /internal/run-sync` with the secret in the `X-Sync-Secret` header. A wrong or missing secret gets `401` and nothing runs. These calls also keep the hosted app awake.
2. **Only one run at a time.** Each run takes a lock (the `sync_runner` row). If another run holds it, the call returns `{"status": "busy"}` immediately. A crashed run's lock expires after 5 minutes.
3. **Cheap change checks.** Every run asks Spotify for each playlist's `snapshot_id` (a version number). Every other run asks YouTube for the playlist's etag (1 quota unit).
4. **Wait for edits to stop.** When a change is seen, the playlist is marked pending but not synced yet. It syncs after **2 runs in a row with no new change** (about 4 minutes), so you're not synced mid-edit.
5. **Compare against the snapshot.** The sync reads both full playlists and compares each with the snapshot from the last sync: songs not in the snapshot were **added**, snapshot songs that are gone were **removed**. Each change is applied to the other platform, and the new snapshot is saved only after all the writes succeed.
6. **Finding the song on the other platform.** If the same song is already on the other side, they're simply paired. Otherwise it's looked up in the song cache, then searched. Songs with no match are left out of the snapshot (so they never look "deleted") and aren't searched again for 24 hours.

### Safety rules

- **`SYNC_DRY_RUN` defaults to `true`.** In dry run the app only logs what it would change. Set it to `false` to make real changes.
- A failed, cut-off (over 1,000 songs) or empty read of a playlist that had songs is treated as an error, and that playlist is skipped for the run. It is never read as "everything was deleted".
- The **first sync** of a playlist only adds songs; it never removes anything.
- Deleted or private YouTube videos are not treated as removals.
- If more than `SYNC_MAX_REMOVALS` (default 10) songs would be removed from one playlist in one run, nothing is changed for that playlist and the problem is logged.
- Adds are matched before removals are decided, so swapping one version of a song for another doesn't delete it.
- Each playlist is synced inside its own error handling, so one failure doesn't stop the others. A failed sync is retried after 10 minutes.
- The app records the platforms' new version markers after its own writes, so its own changes don't trigger another sync.

### Setup

1. Run [`autosync_tables.sql`](autosync_tables.sql) on your database.
2. Set `SYNC_SECRET` (a long random string) in the server's environment. Leave `SYNC_DRY_RUN=true` until you've checked the logs.
3. Create a scheduled job (for example on cron-job.org) that sends `POST https://<your-app>/internal/run-sync` with the header `X-Sync-Secret: <your secret>` every 2 minutes.
4. Watch the server logs. Each run prints what it checked, what it would change (or changed), and the estimated YouTube quota used.

### Limits and quota

Each run checks up to `SYNC_MAX_CHECKS` playlists and syncs up to `SYNC_MAX_PAIRS`, stops starting new work after `SYNC_TIME_BUDGET_SECONDS`, and makes at most `SYNC_MAX_YT_SEARCHES` YouTube searches and `SYNC_MAX_YT_WRITES` YouTube adds/removals. Anything left over carries to the next run. Checking one Keep Synced playlist costs roughly 360 YouTube quota units a day; searches and writes come on top of that.

---

## API Endpoints Reference

| Method   | Endpoint                    | Inputs Required                                              | Returns                                                  |
|----------|-----------------------------|--------------------------------------------------------------|----------------------------------------------------------|
| `GET`    | `/`                         | —                                                            | The app (frontend page)                                  |
| `GET`    | `/privacy`                  | —                                                            | Privacy policy page                                      |
| `GET`    | `/terms`                    | —                                                            | Terms page                                               |
| `GET`    | `/google_auth`              | —                                                            | Redirects user to Google OAuth consent screen            |
| `GET`    | `/google_auth/callback`     | OAuth `code` and `state` (handled by Google redirect)        | Creates or finds the user by Google account, stores YouTube tokens; redirects to Spotify OAuth if Spotify isn't connected yet, otherwise to the dashboard |
| `GET`    | `/spotify_auth`             | `user_id` (query param)                                      | Redirects user to Spotify OAuth consent screen           |
| `GET`    | `/api/spotify/callback`     | OAuth `code` and `state` (handled by Spotify redirect)       | Stores Spotify tokens; redirects to dashboard            |
| `GET`    | `/playlists/{user_id}`      | `user_id` (path param)                                       | Array of all playlists belonging to the user             |
| `GET`    | `/playlist_tracks`          | `name`, `user_id` (query params)                             | Live song list per platform, with status for each        |
| `POST`   | `/create_playlist`          | `name`, `user_id`, `platform`                                | Creates playlist on platform(s) and saves to DB          |
| `POST`   | `/add_playlist`             | `name`, `user_id`, `platform`                                | Finds playlist on platform, imports songs to DB          |
| `POST`   | `/copy_playlist`            | `name`, `user_id`, `platform`, `sync` (bool)                 | Copies playlist to the other platform                    |
| `POST`   | `/sync_playlist`            | `name`, `user_id`, `override_platform`                       | Overwrites one platform's playlist with the other's      |
| `DELETE` | `/delete_playlist`          | `name`, `user_id`, `platform` (query params)                 | Deletes playlist from platform(s) and the DB             |
| `POST`   | `/generate_playlist`        | `name`, `prompt`, `platform`, `user_id`                      | AI-generated playlist; returns added and skipped songs   |
| `POST`   | `/internal/run-sync`        | `X-Sync-Secret` header                                       | Runs one auto-sync pass; `401` if the secret is wrong or missing, `{"status": "busy"}` if a run is already going |
| `POST`   | `/logout`                   | `user_id`                                                    | Clears access tokens in DB                               |
| `DELETE` | `/delete_account`           | `user_id` (query param)                                      | Deletes user account and all associated playlists        |

---

## Notes and Limitations

- **Spotify user limit:** Spotify restricts apps in development mode to **5 users total**, including the developer. To allow more users, you must request a quota extension through the Spotify Developer Dashboard.

- **Playlist name matching:** When using **Add Playlist**, the name you enter must match the playlist name on the platform **exactly** — including spelling and capitalization. When using **Copy Playlist**, **Sync Playlist** or **Delete Playlist**, the name must match exactly what is stored in the database.

- **Add, Copy and Sync Playlist only read the first page of a playlist.** They use older helpers that read a single page of results, so on long playlists they miss songs. The song list window and automatic syncing read every page (up to 1,000 songs).

- **OAuth tokens:** Access tokens are refreshed automatically. If a refresh fails (for example you revoked access), you'll see a "login has expired" message; log out and sign in again.

- **Sync Playlist requires "both" platform:** The Sync Playlist feature only works on playlists whose `platform` field in the database is set to `"both"` — meaning the playlist must already exist on both YouTube and Spotify. If a playlist only exists on one platform, use Copy Playlist first.

- **Copy Playlist requires a single-platform playlist:** Copy Playlist only works on playlists that currently exist on one platform. If the playlist is already tracked on both platforms (platform = `"both"`), it cannot be copied again.

- **Automatic syncing doesn't sync song order.** Added songs go to the end of the other playlist. Local files and podcast episodes on Spotify are ignored. Playlists over 1,000 songs aren't auto-synced (the read is treated as cut off).

- **Automatic syncing isn't instant.** Changes are picked up within a few minutes: it waits for edits to stop, Spotify's version number can take up to about a minute to update, and YouTube is checked every other run.

- **YouTube quota:** The YouTube Data API has a daily quota. Searches (100 units) are the expensive part; the song cache and the per-run limits keep usage down.

- **Deleting your account deletes everything in the app:** Because the `playlists` table has an `ON DELETE CASCADE` foreign key constraint referencing the `users` table, deleting your account will automatically delete all of your playlists from the database as well. Your playlists on Spotify and YouTube stay.

- **Google "unverified app" warning:** During development, Google will show a warning that the app is not verified. This is normal. Click **"Continue"** or **"Advanced > Go to [app name]"** to proceed.

- **Spotify API change (February 2026):** Spotify deprecated the `/tracks` endpoint for playlists. This app uses the updated `/items` endpoint and is fully compatible with the current Spotify API.
