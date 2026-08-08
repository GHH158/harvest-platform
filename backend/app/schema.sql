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

CREATE TABLE IF NOT EXISTS material_playback_state (
    material_id BIGINT PRIMARY KEY REFERENCES material(id) ON DELETE CASCADE,
    position_ms INTEGER NOT NULL DEFAULT 0 CHECK (position_ms >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS trg_material_playback_state_updated ON material_playback_state;
CREATE TRIGGER trg_material_playback_state_updated BEFORE UPDATE ON material_playback_state
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
    reading       TEXT,
    start_ms      INTEGER NOT NULL,
    end_ms        INTEGER NOT NULL,
    UNIQUE (segment_id, idx)
);
ALTER TABLE token ADD COLUMN IF NOT EXISTS reading TEXT;

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
    kind          TEXT NOT NULL, -- fetch|tts|asr|vision|download_video|transcode|upload_video|asr_video|translate_video|shadowing|voice_enrollment|voice_enrollment_video
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

CREATE TABLE IF NOT EXISTS vocabulary (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    word           TEXT NOT NULL,
    reading        TEXT,
    meaning        TEXT NOT NULL,
    part_of_speech TEXT,
    context        TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vocabulary_created ON vocabulary(created_at DESC, id DESC);
-- Cloze-review support: an example sentence to blank the word out of, plus
-- Leitner-style spaced-repetition scheduling (box 1 = review soon, higher = longer gap).
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS example_ja TEXT;
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS example_zh TEXT;
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS box INT NOT NULL DEFAULT 1;
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS review_count INT NOT NULL DEFAULT 0;
ALTER TABLE vocabulary ADD COLUMN IF NOT EXISTS next_review_at TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_vocabulary_next_review ON vocabulary(next_review_at ASC, id ASC);

-- Grammar skeleton (§12). The catalogue is an index, not content: a stable key,
-- a short Chinese label, a level and an ordering. Explanations are generated on
-- demand by the teaching kernel and cached separately, so nothing here is
-- transcribed textbook material.
CREATE TABLE IF NOT EXISTS grammar_point (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key         TEXT NOT NULL UNIQUE,   -- stable identifier, e.g. "i-adj-past"
    title_ja    TEXT NOT NULL,          -- the form itself, e.g. 「～かった」
    title_zh    TEXT NOT NULL,          -- short Chinese label, not an explanation
    level       TEXT NOT NULL,          -- N5 | N4 | N3 …
    category    TEXT NOT NULL,          -- 助词 | 动词变形 | 形容词 | 句型 …
    sort_order  INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_grammar_point_order ON grammar_point(level, sort_order, id);

-- One row per point the learner has any relationship with. Absent row = 未接触.
CREATE TABLE IF NOT EXISTS grammar_encounter (
    point_id          BIGINT PRIMARY KEY REFERENCES grammar_point(id) ON DELETE CASCADE,
    status            TEXT NOT NULL,         -- encountered | understood
    status_source     TEXT NOT NULL DEFAULT 'automatic', -- automatic | manual
    first_source      TEXT,                  -- immutable first contact
    last_source       TEXT,                  -- correction | companion | browse | manual
    note              TEXT,                  -- compatibility snapshot; evidence stays in source tables
    last_evidence_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    browsed_at        TIMESTAMPTZ,
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE grammar_encounter ADD COLUMN IF NOT EXISTS status_source TEXT NOT NULL DEFAULT 'automatic';
ALTER TABLE grammar_encounter ADD COLUMN IF NOT EXISTS last_source TEXT;
ALTER TABLE grammar_encounter ADD COLUMN IF NOT EXISTS last_evidence_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE grammar_encounter ADD COLUMN IF NOT EXISTS browsed_at TIMESTAMPTZ;
ALTER TABLE grammar_encounter ADD COLUMN IF NOT EXISTS status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now();
UPDATE grammar_encounter SET last_source = first_source WHERE last_source IS NULL;
UPDATE grammar_encounter SET browsed_at = created_at
WHERE browsed_at IS NULL AND (first_source = 'browse' OR last_source = 'browse');
-- Before status_source existed, only an explicit user action could create understood.
UPDATE grammar_encounter SET status_source = 'manual'
WHERE status = 'understood' AND status_source <> 'manual';
-- CREATE TRIGGER has no IF NOT EXISTS, and this file re-runs on every startup.
DROP TRIGGER IF EXISTS trg_grammar_encounter_updated ON grammar_encounter;
CREATE TRIGGER trg_grammar_encounter_updated BEFORE UPDATE ON grammar_encounter
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Cache only. Safe to delete at any time; it will be regenerated.
CREATE TABLE IF NOT EXISTS grammar_explanation (
    point_id             BIGINT PRIMARY KEY REFERENCES grammar_point(id) ON DELETE CASCADE,
    content              TEXT NOT NULL,
    prompt_version       TEXT NOT NULL DEFAULT '',
    evidence_fingerprint TEXT NOT NULL DEFAULT '',
    evidence_refs        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE grammar_explanation ADD COLUMN IF NOT EXISTS prompt_version TEXT NOT NULL DEFAULT '';
ALTER TABLE grammar_explanation ADD COLUMN IF NOT EXISTS evidence_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE grammar_explanation ADD COLUMN IF NOT EXISTS evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE grammar_explanation ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
DROP TRIGGER IF EXISTS trg_grammar_explanation_updated ON grammar_explanation;
CREATE TRIGGER trg_grammar_explanation_updated BEFORE UPDATE ON grammar_explanation
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- An explicit companion question is evidence that the learner met a point, but it is
-- not a mistake. Keep the source message and point as a relationship instead of
-- copying the question into grammar_encounter.
CREATE TABLE IF NOT EXISTS companion_grammar_evidence (
    message_id BIGINT NOT NULL REFERENCES companion_message(id) ON DELETE CASCADE,
    point_id   BIGINT NOT NULL REFERENCES grammar_point(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, point_id)
);
CREATE INDEX IF NOT EXISTS idx_companion_grammar_point
    ON companion_grammar_evidence(point_id, created_at DESC);

-- Links a correction back to the grammar skeleton so a real mistake registers the
-- point automatically (§12.1: corrections are the main path, browsing is the补充).
ALTER TABLE chat_correction_item ADD COLUMN IF NOT EXISTS grammar_key TEXT;
CREATE INDEX IF NOT EXISTS idx_correction_item_grammar ON chat_correction_item(grammar_key);
