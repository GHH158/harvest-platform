-- Harvest schema. This mirrors §4.2 of docs/PROJECT.md.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS material (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL, -- reading|video
    title         TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    source_ref    TEXT,
    status        TEXT NOT NULL,
    error_message TEXT,
    duration_ms   INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_material_updated ON material;
CREATE TRIGGER trg_material_updated BEFORE UPDATE ON material
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS segment (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   BIGINT NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    text_ja       TEXT NOT NULL,
    text_zh       TEXT,
    start_ms      INTEGER NOT NULL,
    end_ms        INTEGER NOT NULL,
    UNIQUE (material_id, idx)
);

CREATE TABLE IF NOT EXISTS token (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id    BIGINT NOT NULL REFERENCES segment(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    surface       TEXT NOT NULL,
    start_ms      INTEGER NOT NULL,
    end_ms        INTEGER NOT NULL,
    UNIQUE (segment_id, idx)
);

CREATE TABLE IF NOT EXISTS media_asset (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   BIGINT NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL, -- audio|video
    purpose       TEXT NOT NULL,
    local_path    TEXT,
    oss_key       TEXT,
    bytes         BIGINT,
    duration_ms   INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL, -- fetch|tts|asr|vision|download_video|transcode|upload_video|asr_video|translate_video|shadowing|voice_enrollment
    material_id   BIGINT REFERENCES material(id) ON DELETE CASCADE,
    status        TEXT NOT NULL,
    payload       JSONB,
    error_message TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_job_updated ON job;
CREATE TRIGGER trg_job_updated BEFORE UPDATE ON job
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE INDEX IF NOT EXISTS idx_job_pending ON job(created_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS companion_message (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    material_id   BIGINT NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    segment_id    BIGINT REFERENCES segment(id) ON DELETE SET NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_session (
    id            TEXT PRIMARY KEY,
    topic         TEXT NOT NULL,
    starter_id    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_chat_session_updated ON chat_session;
CREATE TRIGGER trg_chat_session_updated BEFORE UPDATE ON chat_session
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS chat_message (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO chat_session (id, topic)
SELECT DISTINCT session_id,
    CASE WHEN session_id = 'personal' THEN '旧版聊天' ELSE '旧版聊天 · ' || session_id END
FROM chat_message
ON CONFLICT (id) DO NOTHING;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_chat_message_session'
          AND conrelid = 'chat_message'::regclass
    ) THEN
        ALTER TABLE chat_message ADD CONSTRAINT fk_chat_message_session
            FOREIGN KEY (session_id) REFERENCES chat_session(id) ON DELETE CASCADE;
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_chat_session_updated ON chat_session(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_message_session ON chat_message(session_id, id);

CREATE TABLE IF NOT EXISTS chat_correction (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES chat_session(id) ON DELETE CASCADE,
    user_message_id BIGINT NOT NULL UNIQUE REFERENCES chat_message(id) ON DELETE CASCADE,
    original_text   TEXT NOT NULL,
    corrected_text  TEXT NOT NULL,
    summary_zh      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chat_correction_session
    ON chat_correction(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_correction_created
    ON chat_correction(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS chat_correction_item (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correction_id     BIGINT NOT NULL REFERENCES chat_correction(id) ON DELETE CASCADE,
    idx               INTEGER NOT NULL,
    original_fragment TEXT NOT NULL,
    replacement       TEXT NOT NULL,
    reason_zh         TEXT NOT NULL,
    category          TEXT NOT NULL,
    UNIQUE (correction_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_chat_correction_item_category
    ON chat_correction_item(category);

CREATE TABLE IF NOT EXISTS shadowing_attempt (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id    BIGINT NOT NULL REFERENCES segment(id) ON DELETE CASCADE,
    audio_path    TEXT,
    asr_text      TEXT,
    diff_json     JSONB,
    score         REAL,
    job_id        BIGINT REFERENCES job(id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE shadowing_attempt ADD COLUMN IF NOT EXISTS job_id BIGINT REFERENCES job(id) ON DELETE SET NULL;
ALTER TABLE shadowing_attempt ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE shadowing_attempt ADD COLUMN IF NOT EXISTS error_message TEXT;

CREATE TABLE IF NOT EXISTS voice_profile (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT NOT NULL,
    provider      TEXT NOT NULL,
    voice_id      TEXT NOT NULL,
    is_default    BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
