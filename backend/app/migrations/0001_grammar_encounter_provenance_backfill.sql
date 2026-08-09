-- Extracted from schema.sql (§7.5). These fill in provenance for grammar_encounter
-- rows created before last_source / browsed_at / status_source existed (M0).
--
-- The first two are guarded by IS NULL but still belong here: they would keep
-- acting on rows written later, so by the §7.5 two-run test they are migrations,
-- not baseline.
UPDATE grammar_encounter SET last_source = first_source WHERE last_source IS NULL;
UPDATE grammar_encounter SET browsed_at = created_at
WHERE browsed_at IS NULL AND (first_source = 'browse' OR last_source = 'browse');

-- The third had no guard at all and was the reason §7.5 exists. Before
-- status_source existed, only an explicit learner action could produce
-- 'understood', so backfilling those rows to 'manual' is correct — exactly once,
-- for exactly those rows. Left in the baseline it re-ran on every boot, and the
-- moment M4/M5 derives 'understood' automatically it would have rewritten that
-- provenance to 'manual' on the next restart, where §5.10 protects it from
-- automatic correction and it would stick.
UPDATE grammar_encounter SET status_source = 'manual'
WHERE status = 'understood' AND status_source <> 'manual';
