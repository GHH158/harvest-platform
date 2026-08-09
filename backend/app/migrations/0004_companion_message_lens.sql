-- §5.15: record which reading-question angle produced this message.
--
-- The rendered question text is human-readable and could be matched on, but that
-- breaks the moment the wording is reworded, and §5.15's whole success criterion is
-- "did a non-meaning angle ever get used". By §5.11's asymmetry this is a fact, not
-- a projection: if it is not recorded at the moment of asking, it cannot be
-- recovered later. NULL means the learner typed a free question.
ALTER TABLE companion_message ADD COLUMN IF NOT EXISTS lens TEXT;
CREATE INDEX IF NOT EXISTS idx_companion_message_lens
    ON companion_message(lens, created_at DESC) WHERE lens IS NOT NULL;
