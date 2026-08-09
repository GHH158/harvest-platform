-- Extracted from schema.sql (§7.5). The baseline used DROP INDEX + CREATE INDEX
-- to express an index redefinition, which meant every single boot dropped and
-- rebuilt this index. An index definition change is a one-time structural change;
-- the baseline now uses CREATE INDEX IF NOT EXISTS and this migration performs the
-- redefinition once for any database still holding the earlier shape.
DROP INDEX IF EXISTS idx_learner_memory_active;
CREATE INDEX idx_learner_memory_active
    ON learner_memory(kind, latest_evidence_at DESC);
