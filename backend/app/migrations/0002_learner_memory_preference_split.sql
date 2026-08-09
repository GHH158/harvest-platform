-- Extracted from schema.sql (§7.5). M1-C stored the suppression flag on the
-- derived learner_memory row itself; §5.12 split it into learner_memory_preference
-- so that a long-term "stop mentioning this" decision survives the derived row
-- being deleted when its evidence disappears.
--
-- This is a genuine one-shot data move. Re-running it on every boot meant the
-- UPDATE kept scanning learner_memory forever for a column the runtime no longer
-- writes, and any future reuse of that legacy column would have been silently
-- harvested into preferences.
INSERT INTO learner_memory_preference (kind, subject_kind, subject_key, dismissed_at)
SELECT kind, subject_kind, subject_key, dismissed_at
FROM learner_memory WHERE dismissed_at IS NOT NULL
ON CONFLICT (kind, subject_kind, subject_key) DO UPDATE SET
    dismissed_at = LEAST(learner_memory_preference.dismissed_at, EXCLUDED.dismissed_at);
UPDATE learner_memory SET dismissed_at = NULL WHERE dismissed_at IS NOT NULL;
