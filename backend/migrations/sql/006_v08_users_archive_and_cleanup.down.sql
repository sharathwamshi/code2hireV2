-- Code2Hire V02.00.08 · migration 006 rollback. Run before going back to V02.00.07 code.
-- V02.00.07 has no "archived" state, so deleted users stay as switched-off (inactive) users that can't sign in;
-- then the two columns go. The question and name fixes are not undone: they are safe on V02.00.07 too.
UPDATE users SET active = 0 WHERE archived_at IS NOT NULL;
-- removed candidates go back to the stage they had (V02.00.07 has no "removed" stage); voided rounds stay as they are
UPDATE applications SET stage = COALESCE(removed_stage, 'rejected') WHERE stage = 'removed';
DROP TABLE IF EXISTS pool_removals;
ALTER TABLE applications DROP COLUMN removed_stage;
ALTER TABLE applications DROP COLUMN removed_by;
ALTER TABLE applications DROP COLUMN removed_at;
ALTER TABLE users DROP COLUMN archived_by;
ALTER TABLE users DROP COLUMN archived_at;
