-- Rollback 002 · DESTROYS folders, question version history and portal links.
-- Questions themselves are kept (only the new columns are dropped).
DROP TABLE IF EXISTS invite_links;
DROP TABLE IF EXISTS question_versions;
ALTER TABLE candidate_profiles DROP INDEX ix_candidate_profiles_source_company_id, DROP COLUMN source_company_id, DROP COLUMN added_by;
ALTER TABLE questions DROP INDEX ix_questions_folder_id,
    DROP COLUMN folder_id, DROP COLUMN version, DROP COLUMN tags, DROP COLUMN time_seconds, DROP COLUMN updated_by, DROP COLUMN updated_at;
DROP TABLE IF EXISTS question_folders;
