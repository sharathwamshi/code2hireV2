-- =====================================================================================================
-- Code2Hire V02.00.11 · migration 009: candidate interview bug report (CAN-001 to CAN-022).
--   1. new table resume_files   (CAN-002 / CAN-014: the uploaded resume file is kept, with versions)
--   2. jobs.history       JSON  (CAN-018: who changed what on a job, and how many applicants were rescored)
-- Also new in this release, with no schema change:
--   - jobs.status can be 'archived' (VARCHAR already)
--   - MCQ papers are stored in round_attempts.result (JSON already): drawn at invite, reviewed, then started
--   - settings mcq.paper, mcq.review_before_start, mcq.fixed_ids live in the existing settings tables
-- MySQL 8 / MariaDB 10.6+. Run after 008. Back up first. Safe to re-run.
--   mysql -u USER -p DBNAME < 009_v11_resume_files_job_history.up.sql
-- Resume FILES are kept on the server's disk under UPLOAD_DIR/resumes/: back that folder up with the database.
-- =====================================================================================================

CREATE TABLE IF NOT EXISTS resume_files (
  id INTEGER NOT NULL AUTO_INCREMENT,
  created_at DATETIME NOT NULL,
  user_id INTEGER NOT NULL,
  filename VARCHAR(200) NOT NULL,
  kind VARCHAR(8) NOT NULL,
  size INTEGER NULL,
  file_key VARCHAR(80) NOT NULL,
  chars INTEGER NULL,
  status VARCHAR(12) NOT NULL,
  uploaded_by INTEGER NULL,
  PRIMARY KEY (id),
  FOREIGN KEY(user_id) REFERENCES users (id)
);
SET @c := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'resume_files' AND INDEX_NAME = 'ix_resume_files_user_id');
SET @s := IF(@c = 0, 'CREATE INDEX ix_resume_files_user_id ON resume_files (user_id)', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
SET @c := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'resume_files' AND INDEX_NAME = 'ix_resume_files_status');
SET @s := IF(@c = 0, 'CREATE INDEX ix_resume_files_status ON resume_files (status)', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'jobs' AND COLUMN_NAME = 'history');
SET @s := IF(@c = 0, 'ALTER TABLE jobs ADD COLUMN history JSON NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
