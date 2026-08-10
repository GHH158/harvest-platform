-- §5.16: a question asked from the home screen has no material behind it.
--
-- Reuses companion_message rather than adding a table: the grammar-evidence path
-- (companion_grammar_evidence -> companion_message.id), the companion_question
-- learning event and the delete trigger are all already wired to it, and none of
-- them care whether a material exists. material_id IS NULL now means "asked on its
-- own"; such rows are correctly unaffected by material deletion.
ALTER TABLE companion_message ALTER COLUMN material_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS idx_companion_message_standalone
    ON companion_message(created_at DESC) WHERE material_id IS NULL;
