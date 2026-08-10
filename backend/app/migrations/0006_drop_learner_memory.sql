-- Cross-session learner profile removed (2026-08-09).
--
-- `learner_memory` was entirely derived from `learning_event` and could always be
-- recomputed, so dropping it loses no fact. `learner_memory_preference` held the one
-- non-derived thing — "stop mentioning this category" — and was empty.
--
-- What it did: turn recurring correction categories into a sentence injected into the
-- chat system prompt. The grammar shelf already shows the same information *visibly*
-- and the learner can act on it; this was the invisible copy, so there was no way to
-- tell whether it helped. The visible one stayed (§12), this one goes.
DROP TABLE IF EXISTS learner_memory_preference;
DROP TABLE IF EXISTS learner_memory;
