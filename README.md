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
9. [How to Use the App](#how-to-use-the-app)
   - [Creating an Account](#creating-an-account)
   - [Logging In](#logging-in)
   - [Create Playlist](#create-playlist)
   - [Add Playlist](#add-playlist)
   - [Copy Playlist](#copy-playlist)
   - [Sync Playlist](#sync-playlist)
   - [Delete Playlist](#delete-playlist)
   - [Logout](#logout)
   - [Delete Account](#delete-account)
10. [API Endpoints Reference](#api-endpoints-reference)
11. [Notes and Limitations](#notes-and-limitations)

---

## Features

- **Create Playlists** — Create a new empty playlist on YouTube, Spotify, or both platforms simultaneously from the dashboard.
- **Add an Existing Playlist** — Import a playlist that already exists on YouTube or Spotify into the app's database so it can be managed alongside your other playlists.
- **Copy a Playlist** — Copy a playlist from one platform to the other. The app searches for each song on the target platform and recreates the playlist there.
- **Sync Playlists** — For playlists that live on both platforms, pick one as the source of truth and overwrite the other platform's version with its songs.
- **Delete a Playlist** — Remove a playlist from one platform, both platforms, or just the database.
- **Generate with AI** — Describe the music you want (e.g. "pumped up workout music") and Claude suggests about 20 real songs. Each song is searched and verified on Spotify and/or YouTube before it's added; songs that can't be found are skipped and listed with the reason.
- **Logout** — Securely log out of your session. Clears your OAuth access tokens from the database and returns you to the login page, requiring full re-authentication on your next visit.
- **Delete Your Account** — Permanently remove your account and all associated playlists from the database with a single confirmation.

---

## Tech Stack

| Layer      | Technology                                                  |
|------------|-------------------------------------------------------------|
| Language   | Python 3.x                                                  |
| Framework  | FastAPI                                                     |
| DB Driver  | psycopg2                                                    |
| Database   | PostgreSQL                                                  |
| Auth       | bcrypt (passwords), Google OAuth2, Spotify OAuth2           |
| APIs       | Google YouTube Data API v3, Spotify Web API                 |
| Frontend   | Vanilla HTML, CSS, JavaScript                               |
| Other      | python-dotenv, google-auth, google-auth-oauthlib, requests  |

---

## Prerequisites

Before running this project, make sure you have the following installed and configured:

- **Python 3.x** — [https://www.python.org/downloads/](https://www.python.org/downloads/)
- **PostgreSQL** — [https://www.postgresql.org/download/](https://www.postgresql.org/download/)
- **A Google Cloud Console account** with a project that has the YouTube Data API v3 enabled and OAuth 2.0 credentials configured (see [Google Cloud Console Setup](#google-cloud-console-setup))
- **A Spotify Developer account** with an app created in the Spotify Developer Dashboard (see [Spotify Developer Setup](#spotify-developer-setup))

### Python Dependencies

Install all required packages with:

```bash
pip install fastapi uvicorn psycopg2 bcrypt requests python-dotenv google-auth google-auth-oauthlib google-auth-httplib2
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

# Optional (defaults shown)
AI_DAILY_LIMIT=5
AI_GLOBAL_DAILY_LIMIT=100
```

| Variable                  | Description                                                                                         |
|---------------------------|-----------------------------------------------------------------------------------------------------|
| `DATABASE_URL`            | PostgreSQL connection string. Replace `username`, `password`, and `database_name` with your values. |
| `GOOGLE_CLIENT_ID`        | The OAuth 2.0 Client ID from your Google Cloud Console project.                                     |
| `GOOGLE_CLIENT_SECRET_KEY`| The OAuth 2.0 Client Secret from your Google Cloud Console project.                                 |
| `GOOGLE_REDIRECT_URL`     | The redirect URI registered in Google Cloud Console. Must be `http://127.0.0.1:8000/google_auth/callback`. |
| `GOOGLE_REDIRECT_URI`     | Same as above — both variables are used in different parts of the backend.                          |
| `SPOTIFY_CLIENT_ID`       | The Client ID from your app in the Spotify Developer Dashboard.                                     |
| `SPOTIFY_CLIENT_SECRET`   | The Client Secret from your app in the Spotify Developer Dashboard.                                 |
| `SPOTIFY_REDIRECT_URI`    | The redirect URI registered in Spotify. Must be `http://127.0.0.1:8000/api/spotify/callback`.       |
| `ANTHROPIC_API_KEY`       | Claude API key for Generate with AI. Server-side only — never sent to the browser. On Render, set it under Environment. |
| `AI_DAILY_LIMIT`          | Optional. AI generations per user per day (UTC). Default `5`.                                       |
| `AI_GLOBAL_DAILY_LIMIT`   | Optional. AI generations across all users per day (UTC). Default `100`. Caps daily API spend.       |

---

## Database Setup

1. Open **pgAdmin** (or any PostgreSQL query tool) and create a new database. You can name it anything — just make sure the name matches what you put in `DATABASE_URL`.

2. Open the query tool for your new database and run the following SQL **all at once**. You can copy and paste the entire block and execute it with no modifications:

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TYPE platform_enum AS ENUM ('youtube', 'spotify', 'both');

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
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

-- Generate with AI: cache of verified matches (saves YouTube quota)
CREATE TABLE song_cache (
    title_key TEXT NOT NULL,
    artist_key TEXT NOT NULL,
    spotify_track_id TEXT,
    youtube_video_id TEXT,
    updated_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (title_key, artist_key)
);
```

> **Important:** The `pgcrypto` extension must be enabled first — it provides `gen_random_uuid()` used to generate UUID primary keys. The `platform_enum` type must be created before the tables. Both tables use UUIDs as primary keys rather than auto-incrementing integers, which prevents sequential ID enumeration.

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

4. Once the server is running, open `index.html` in your browser.

> **Important:** The backend must be running at `http://127.0.0.1:8000` **before** you open the frontend. If the backend is not running, all API calls from the frontend will fail.

---

## How to Use the App

### Creating an Account

1. On the login page, click **"Create Account"**.
2. Enter a username (minimum 2 characters) and a password, then click **"Verify"**.
3. The app will automatically redirect you to **Google OAuth** — sign in with your Google account and grant permission to manage your YouTube playlists.
4. Immediately after, you will be redirected to **Spotify OAuth** — log in with your Spotify account and grant permission to manage your Spotify playlists.
5. Once both authorizations are complete, your account is fully set up and you can log in.

### Logging In

1. Enter your username and password on the login page and click **"Login"**.
2. If your OAuth tokens are still valid, you will be taken directly to the dashboard.
3. If your tokens have expired, the app will automatically redirect you through Google and/or Spotify OAuth again to re-authenticate. This is normal behavior — OAuth tokens have a limited lifespan.

---

### Create Playlist

**What it does:** Creates a new empty playlist and saves it to the database.

**How to use it:**
- Click **"Create Playlist"** in the navbar.
- Enter a playlist name.
- Select a platform: **Both** (default), **YouTube**, or **Spotify**.
  - Selecting **Both** creates the playlist on YouTube and Spotify at the same time.
  - Selecting a single platform only creates it there.
- Click **"Create"**.

The playlist will appear on your dashboard once created.

**Backend endpoint:** `POST /create_playlist`

---

### Add Playlist

**What it does:** Imports a playlist that already exists on YouTube or Spotify into the app's database so it can be managed from the dashboard.

**How to use it:**
- Click **"Add Playlist"** in the navbar.
- Enter the playlist name **exactly as it appears on the platform** — spelling and capitalization must match exactly.
- Select the platform the playlist lives on (**YouTube** or **Spotify**).
- Click **"Add"**.

The app will find the playlist on the selected platform, pull its songs, save everything to the database, and display the playlist on your dashboard.

**Backend endpoint:** `POST /add_playlist`

---

### Copy Playlist

**What it does:** Copies a playlist from one platform to the other. The app searches for each song on the target platform and adds them to a newly created playlist there.

**How to use it:**
- Click **"Copy Playlist"** in the navbar.
- Enter the playlist name **exactly as it appears in the database**.
- Select the platform the playlist currently lives on (**YouTube** or **Spotify**) — the app will copy it to the other platform.
- Optionally check **"Keep Synced?"** — this tracks both versions going forward so you can use Sync Playlist on it later.
- Click **"Copy"**.

**Backend endpoint:** `POST /copy_playlist`

---

### Sync Playlist

**What it does:** For playlists that exist on both platforms, this overwrites one platform's version with the other. One platform is designated the "source of truth" and its songs completely replace whatever is on the other platform.

**How to use it:**
- Click **"Sync Playlist"** in the navbar.
- Enter the playlist name exactly as it appears in the database.
- Select the **Source of Truth Platform** — whichever platform you pick, its current songs will be pushed to the other platform, replacing everything there.
  - For example: selecting **YouTube** will push all songs from the YouTube playlist into Spotify, overwriting the Spotify version.
- Click **"Sync"**.

> This feature only works on playlists whose platform is set to **"both"** in the database (i.e., playlists that exist on both platforms).

**Backend endpoint:** `POST /sync_playlist`

---

### Delete Playlist

**What it does:** Deletes a playlist from one or both platforms and removes it from the database.

**How to use it:**
- Click **"Delete Playlist"** in the navbar.
- Enter the playlist name exactly as it appears in the database.
- Select the platform:
  - **Both** — deletes the playlist from YouTube, Spotify, and the database.
  - **YouTube** or **Spotify** — deletes it from only that platform.
- Click **"Delete"**.

**Backend endpoint:** `DELETE /delete_playlist`

---

### Generate with AI

**What it does:** Builds a new playlist from a short description using Claude (`claude-haiku-5-5`).

**How to use it:**
- Open **Actions > Generate with AI**.
- Enter a playlist name and describe the music (up to 300 characters).
- Pick **Both** (default), **Spotify**, or **YouTube**. **Both** turns on Keep Synced and only adds songs found on both platforms.
- Click **Generate**. It can take up to a minute. When it finishes you'll see "Added X of Y songs" plus any skipped songs and why.

**How it works:** Claude returns up to 20 songs as JSON. Each song is checked against the song cache, then searched on the platform. The top results must match the title and artist loosely (case, "feat.", "(Remastered)" and similar extras are ignored), and on YouTube official uploads (VEVO, "- Topic", the artist's own channel) are preferred. Songs that don't match are skipped. Each user gets `AI_DAILY_LIMIT` generations per day, and there's an overall `AI_GLOBAL_DAILY_LIMIT`; both are checked before Claude is called.

**Backend endpoint:** `POST /generate_playlist`

---

### Logout

**What it does:** Ends your current session securely. Clears your YouTube and Spotify access tokens from the database (refresh tokens are preserved so re-authentication is smooth), removes your session from the browser, and returns you to the login page.

**How to use it:**
- Click **"Logout"** in the navbar (styled in red).
- A confirmation modal will appear asking "Are you sure you want to log out?"
- Click **"Logout"** to confirm, or **"Cancel"** to close the modal and stay on the dashboard.

> The next time you log in, the backend will detect that your access tokens are cleared and redirect you through Google and/or Spotify OAuth to re-authenticate. This is expected — your playlists and account data are fully preserved.

**Backend endpoint:** `POST /logout`

---

### Delete Account

**What it does:** Permanently deletes your user account and all your playlists from the database.

**How to use it:**
- Click **"Delete Account"** in the navbar (styled in red).
- A confirmation dialog will appear. Confirm to proceed.

> **This action cannot be undone.** All playlists associated with your account are also deleted due to the `ON DELETE CASCADE` constraint on the playlists table.

**Backend endpoint:** `DELETE /delete_account`

---

## API Endpoints Reference

| Method   | Endpoint                    | Inputs Required                                              | Returns                                                  |
|----------|-----------------------------|--------------------------------------------------------------|----------------------------------------------------------|
| `POST`   | `/create_user`              | `username`, `password`                                       | New user record; redirects through Google + Spotify OAuth |
| `POST`   | `/login`                    | `username`, `password`                                       | `user_id` and token validation status                     |
| `GET`    | `/google_auth`              | `user_id` (query param)                                      | Redirects user to Google OAuth consent screen            |
| `GET`    | `/google_auth/callback`     | OAuth `code` and `state` (handled by Google redirect)        | Stores YouTube tokens; redirects to Spotify OAuth        |
| `GET`    | `/spotify_auth`             | `user_id` (query param)                                      | Redirects user to Spotify OAuth consent screen           |
| `GET`    | `/api/spotify/callback`     | OAuth `code` and `state` (handled by Spotify redirect)       | Stores Spotify tokens; redirects to dashboard            |
| `GET`    | `/playlists/{user_id}`      | `user_id` (path param)                                       | Array of all playlists belonging to the user             |
| `POST`   | `/create_playlist`          | `name`, `user_id`, `platform`                                | Creates playlist on platform(s) and saves to DB          |
| `POST`   | `/add_playlist`             | `name`, `user_id`, `platform`                                | Finds playlist on platform, imports songs to DB          |
| `POST`   | `/copy_playlist`            | `name`, `user_id`, `platform`, `sync` (bool)                 | Copies playlist to the other platform                    |
| `POST`   | `/sync_playlist`            | `name`, `user_id`, `override_platform`                       | Overwrites one platform's playlist with the other's      |
| `DELETE` | `/delete_playlist`          | `name`, `user_id`, `platform`                                | Deletes playlist from platform(s) and/or DB              |
| `POST`   | `/generate_playlist`        | `name`, `prompt`, `platform`, `user_id`                      | AI-generated playlist; returns added and skipped songs   |
| `POST`   | `/logout`                   | `user_id`                                                    | Clears access tokens in DB; user must re-auth on login   |
| `DELETE` | `/delete_account`           | `user_id`                                                    | Deletes user account and all associated playlists        |

---

## Notes and Limitations

- **Spotify user limit:** Spotify restricts apps in development mode to **5 users total**, including the developer. To allow more users, you must request a quota extension through the Spotify Developer Dashboard.

- **Playlist name matching:** When using **Add Playlist**, the name you enter must match the playlist name on the platform **exactly** — including spelling and capitalization. When using **Copy Playlist** or **Sync Playlist**, the name must match exactly what is stored in the database.

- **OAuth token expiration:** OAuth tokens expire periodically. If your tokens have expired when you log in, you will be automatically redirected through Google and/or Spotify OAuth to re-authenticate. This is expected behavior and does not indicate an error.

- **Sync Playlist requires "both" platform:** The Sync Playlist feature only works on playlists whose `platform` field in the database is set to `"both"` — meaning the playlist must already exist on both YouTube and Spotify. If a playlist only exists on one platform, use Copy Playlist first.

- **Copy Playlist requires a single-platform playlist:** Copy Playlist only works on playlists that currently exist on one platform. If the playlist is already tracked on both platforms (platform = `"both"`), it cannot be copied again.

- **Deleting your account deletes everything:** Because the `playlists` table has an `ON DELETE CASCADE` foreign key constraint referencing the `users` table, deleting your account will automatically delete all of your playlists from the database as well.

- **Google "unverified app" warning:** During development, Google will show a warning that the app is not verified. This is normal. Click **"Continue"** or **"Advanced > Go to [app name]"** to proceed.

- **Spotify API change (February 2026):** Spotify deprecated the `/tracks` endpoint for playlists. This app uses the updated `/items` endpoint and is fully compatible with the current Spotify API.
