-- Harvest schema. This mirrors §4.2 of docs/PROJECT.md.
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS material (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL,
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
    kind          TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    local_path    TEXT,
    oss_key       TEXT,
    bytes         BIGINT,
    duration_ms   INTEGER,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind          TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS chat_message (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
