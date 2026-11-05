-- Code2Hire V02.00.04 · migration 004 rollback. Removes the recordings table (video FILES are not deleted).
-- Data fixes (settings limits, archived duplicate questions, removed call.record rows) are not undone.
DROP TABLE IF EXISTS recordings;
