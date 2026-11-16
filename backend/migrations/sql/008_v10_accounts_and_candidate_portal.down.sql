-- Code2Hire V02.00.10 · undo migration 008. Removes saved jobs, path details and candidate product feedback.
-- Back up first: product feedback is deleted. Reset links stay in invite_links and stop working on V02.00.09.
DROP TABLE IF EXISTS product_feedback;
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'learning_paths' AND COLUMN_NAME = 'meta');
SET @s := IF(@c = 1, 'ALTER TABLE learning_paths DROP COLUMN meta', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'candidate_profiles' AND COLUMN_NAME = 'saved_jobs');
SET @s := IF(@c = 1, 'ALTER TABLE candidate_profiles DROP COLUMN saved_jobs', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
UPDATE invite_links SET revoked = 1 WHERE purpose = 'reset' AND used_at IS NULL;
