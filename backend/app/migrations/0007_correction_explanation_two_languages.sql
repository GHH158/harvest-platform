-- §18.2: the correction explanation columns were named `_zh` but had been holding
-- Japanese all along.
--
-- Measured before writing this: 12 of 13 `chat_correction.summary_zh` rows and 15 of 16
-- `chat_correction_item.reason_zh` rows contain kana. The prompt said "Explain briefly in
-- Chinese"; the model ignored that instruction in all but one row of each, the output
-- was good, and nobody noticed because the field name was never checked against the data.
-- (Deliberately no percent sign anywhere in this file: it runs through exec_driver_sql,
-- where a bare percent is read as a parameter placeholder even inside a comment. That
-- mistake cost one debugging round on the way in.) The learner's own
-- words when asked: 「保持现在的这种日语讲解内容就挺好的,加一个中文讲解即可吧」 — they
-- had been reading Japanese explanations and want them kept.
--
-- So this renames to match reality (a label correction, not a data move) and adds real
-- Chinese columns beside them.
--
-- Guarded so it is a no-op on a database created fresh from schema.sql, where the
-- CREATE TABLE already declares both columns and there is nothing to rename.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_correction' AND column_name = 'summary_zh'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_correction' AND column_name = 'summary_ja'
    ) THEN
        ALTER TABLE chat_correction RENAME COLUMN summary_zh TO summary_ja;
        ALTER TABLE chat_correction ALTER COLUMN summary_ja DROP NOT NULL;
        ALTER TABLE chat_correction ADD COLUMN summary_zh TEXT;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_correction_item' AND column_name = 'reason_zh'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chat_correction_item' AND column_name = 'reason_ja'
    ) THEN
        ALTER TABLE chat_correction_item RENAME COLUMN reason_zh TO reason_ja;
        ALTER TABLE chat_correction_item ALTER COLUMN reason_ja DROP NOT NULL;
        ALTER TABLE chat_correction_item ADD COLUMN reason_zh TEXT;
    END IF;
END $$;

-- The handful of rows that really were Chinese must not be relabelled as Japanese just
-- because the bulk of them were. Kana is the test: no kana at all means it is not
-- Japanese, so the text belongs in the Chinese column and the Japanese one is genuinely
-- absent for that row. One row of each at the time of writing — but it is the learner's
-- own learning history, and mislabelling two rows to save a WHERE clause is not a trade
-- worth making.
UPDATE chat_correction
   SET summary_zh = summary_ja,
       summary_ja = NULL
 WHERE summary_ja IS NOT NULL
   AND summary_zh IS NULL
   AND summary_ja !~ '[ぁ-ゖァ-ヺ]';

UPDATE chat_correction_item
   SET reason_zh = reason_ja,
       reason_ja = NULL
 WHERE reason_ja IS NOT NULL
   AND reason_zh IS NULL
   AND reason_ja !~ '[ぁ-ゖァ-ヺ]';
