-- =====================================================================================================
-- Code2Hire V02.00.10 · migration 008: candidate portal redesign and accounts.
--   1. candidate_profiles.saved_jobs  JSON  (jobs a candidate bookmarked)
--   2. learning_paths.meta           JSON  (goal, "basic outline" flag, the application the path leads to)
--   3. new table product_feedback          (feedback candidates send to Code2Hire, read by the superadmin)
-- Forgot password, SMTP settings and staff editing need no schema change: reset links use invite_links
-- (purpose = 'reset'), SMTP settings are platform secrets, and "candidates.edit" is a permission in code.
-- MySQL 8 / MariaDB 10.6+. Run after 007. Back up first. Safe to re-run.
--   mysql -u USER -p DBNAME < 008_v10_accounts_and_candidate_portal.up.sql
-- =====================================================================================================

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'candidate_profiles' AND COLUMN_NAME = 'saved_jobs');
SET @s := IF(@c = 0, 'ALTER TABLE candidate_profiles ADD COLUMN saved_jobs JSON NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'learning_paths' AND COLUMN_NAME = 'meta');
SET @s := IF(@c = 0, 'ALTER TABLE learning_paths ADD COLUMN meta JSON NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

CREATE TABLE IF NOT EXISTS product_feedback (
  id INTEGER NOT NULL AUTO_INCREMENT,
  created_at DATETIME NOT NULL,
  user_id INTEGER NULL,
  topics JSON NULL,
  rating INTEGER NULL,
  text TEXT NULL,
  page VARCHAR(120) NULL,
  status VARCHAR(20) NULL,
  PRIMARY KEY (id),
  FOREIGN KEY(user_id) REFERENCES users (id)
);
SET @c := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'product_feedback' AND INDEX_NAME = 'ix_product_feedback_user_id');
SET @s := IF(@c = 0, 'CREATE INDEX ix_product_feedback_user_id ON product_feedback (user_id)', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- Optional (CER-05): list test certifications left on the live site before deciding what to archive. Nothing is changed.
-- SELECT id, name, created_at FROM certs WHERE LOWER(name) LIKE '%test%' OR LOWER(name) LIKE '%demo%';
