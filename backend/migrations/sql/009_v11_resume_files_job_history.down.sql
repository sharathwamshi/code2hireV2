-- Code2Hire V02.00.11 · undo migration 009. Back up first: resume file records and job edit history are deleted.
-- The files under UPLOAD_DIR/resumes/ are left on disk; remove that folder by hand if you want them gone.
-- Archived jobs are set back to closed, because V02.00.10 doesn't know the 'archived' status.
UPDATE jobs SET status = 'closed' WHERE status = 'archived';
DROP TABLE IF EXISTS resume_files;
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'jobs' AND COLUMN_NAME = 'history');
SET @s := IF(@c = 1, 'ALTER TABLE jobs DROP COLUMN history', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
