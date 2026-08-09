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

-- Immutable review history (M1-B, §5.11). vocabulary.box/review_count/next_review_at
-- stay the mutable scheduling projection the review flow reads and writes; this table
-- is the append-only fact log neither of those columns can answer questions from
-- ("which attempt, correct or not, what box transition") since a counter cannot be
-- unwound into individual past events. Reviews before this table existed have no
-- recoverable history; do not backfill by guessing from review_count (§5.11).
CREATE TABLE IF NOT EXISTS vocabulary_review_attempt (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vocabulary_id BIGINT NOT NULL REFERENCES vocabulary(id) ON DELETE CASCADE,
    correct       BOOLEAN NOT NULL,
    box_before    INT NOT NULL,
    box_after     INT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_vocabulary_review_attempt_word
    ON vocabulary_review_attempt(vocabulary_id, created_at DESC);

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

-- Global learning events (M1, full contract in §5.11 of docs/PROJECT.md). A thin
-- envelope plus a payload validated by `kind` at the application layer, not here:
-- the source row's original text stays in its own table, this only stores a
-- reference and a necessary snapshot. chat_correction_item.grammar_key and
-- companion_grammar_evidence keep being written for traceability, but the
-- grammar_encounter projection reads this table instead.
CREATE TABLE IF NOT EXISTS learning_event (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'learning-event-v1',
    kind           TEXT NOT NULL,       -- correction_item | companion_question | vocabulary_saved
                                         -- | vocabulary_reviewed | shadowing_completed (§5.11)
    source_table   TEXT NOT NULL,
    source_id      BIGINT NOT NULL,
    subject_kind   TEXT NOT NULL,       -- grammar_point | vocabulary_word | segment (§5.11)
    subject_key    TEXT NOT NULL,
    actor          TEXT NOT NULL DEFAULT 'user',
    confidence     REAL,
    occurred_at    TIMESTAMPTZ NOT NULL,
    backfilled     BOOLEAN NOT NULL DEFAULT false,
    rejected_at    TIMESTAMPTZ,
    payload        JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_table, source_id, subject_kind, subject_key)
);
CREATE INDEX IF NOT EXISTS idx_learning_event_subject
    ON learning_event(subject_kind, subject_key, occurred_at DESC)
    WHERE rejected_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_learning_event_source ON learning_event(source_table, source_id);

-- Polymorphic source references cannot use one foreign key. Source-row deletion
-- still has to remove its event envelope, including cascades from deleting a chat
-- session or material, so keep that invariant next to the tables themselves.
CREATE OR REPLACE FUNCTION delete_learning_events_for_source() RETURNS TRIGGER AS $$
BEGIN
    DELETE FROM learning_event
    WHERE source_table = TG_TABLE_NAME AND source_id = OLD.id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_correction_item_learning_event_delete ON chat_correction_item;
CREATE TRIGGER trg_correction_item_learning_event_delete
    AFTER DELETE ON chat_correction_item
    FOR EACH ROW EXECUTE FUNCTION delete_learning_events_for_source();
DROP TRIGGER IF EXISTS trg_companion_message_learning_event_delete ON companion_message;
CREATE TRIGGER trg_companion_message_learning_event_delete
    AFTER DELETE ON companion_message
    FOR EACH ROW EXECUTE FUNCTION delete_learning_events_for_source();
-- M1-B (§5.11): vocabulary_review_attempt cascades from vocabulary (ON DELETE CASCADE),
-- so deleting a word converges both its vocabulary_saved event and every
-- vocabulary_reviewed event from its own trigger below — no orphaned rows either way.
DROP TRIGGER IF EXISTS trg_vocabulary_learning_event_delete ON vocabulary;
CREATE TRIGGER trg_vocabulary_learning_event_delete
    AFTER DELETE ON vocabulary
    FOR EACH ROW EXECUTE FUNCTION delete_learning_events_for_source();
DROP TRIGGER IF EXISTS trg_vocabulary_review_attempt_learning_event_delete ON vocabulary_review_attempt;
CREATE TRIGGER trg_vocabulary_review_attempt_learning_event_delete
    AFTER DELETE ON vocabulary_review_attempt
    FOR EACH ROW EXECUTE FUNCTION delete_learning_events_for_source();
DROP TRIGGER IF EXISTS trg_shadowing_attempt_learning_event_delete ON shadowing_attempt;
CREATE TRIGGER trg_shadowing_attempt_learning_event_delete
    AFTER DELETE ON shadowing_attempt
    FOR EACH ROW EXECUTE FUNCTION delete_learning_events_for_source();
