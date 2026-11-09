-- Auto-sync tables for "Keep Synced" playlists (playlists.platform = 'both').
-- Run this by hand against the Neon dev branch first, then prod.
-- Every table cascades on playlist delete, so deleting a playlist cleans these up.

-- One row per matched song per pair. This is "what both sides agreed on
-- after the last successful sync". Songs with no match on the other
-- platform are never stored here, so they can't look deleted later.
CREATE TABLE IF NOT EXISTS sync_snapshot (
    pair_id          uuid        NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    spotify_track_id text        NOT NULL,
    youtube_video_id text        NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pair_id, spotify_track_id, youtube_video_id)
);

-- Change detection + settle check, one row per pair.
CREATE TABLE IF NOT EXISTS sync_state (
    pair_id                       uuid        PRIMARY KEY REFERENCES playlists(id) ON DELETE CASCADE,
    spotify_snapshot_id           text,
    youtube_etag                  text,
    pending                       boolean     NOT NULL DEFAULT true,   -- a change was seen and not synced yet
    last_change_seen_at           timestamptz,
    quiet_runs                    integer     NOT NULL DEFAULT 0,      -- runs in a row with no new change
    youtube_checked_since_change  boolean     NOT NULL DEFAULT false,
    last_checked_at               timestamptz,                         -- oldest first = carry-over order
    last_synced_at                timestamptz,
    last_error                    text,
    last_error_at                 timestamptz
);

-- Songs we searched for and couldn't match, so we don't spend
-- 100 YouTube quota units re-searching them every sync.
CREATE TABLE IF NOT EXISTS sync_unmatched (
    pair_id         uuid        NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    source_platform text        NOT NULL CHECK (source_platform IN ('spotify', 'youtube')),
    source_id       text        NOT NULL,   -- Spotify track id or YouTube video id
    title           text,
    artist          text,
    reason          text,
    last_tried_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pair_id, source_platform, source_id)
);

-- Single-row lease so two runs never overlap. Works through Neon's
-- PgBouncer pooler (session advisory locks don't). A crashed run's lease
-- expires on its own after a few minutes.
CREATE TABLE IF NOT EXISTS sync_runner (
    id                   integer     PRIMARY KEY CHECK (id = 1),
    run_id               uuid,
    running_since        timestamptz,
    run_count            bigint      NOT NULL DEFAULT 0,   -- parity decides the YouTube-check runs
    last_run_finished_at timestamptz,
    last_run_summary     jsonb
);
INSERT INTO sync_runner (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Stage 3 addition: YouTube's etag only covers the first 50 items, so we
-- remember the item count to know which playlists need the 15-minute
-- full re-check.
ALTER TABLE sync_state ADD COLUMN IF NOT EXISTS youtube_item_count integer;
