-- =====================================================================================================
-- Code2Hire V02.00.08 · migration 006: deleted users are archived (SA-002/003), removing and restoring candidates
-- (applications.removed_*, pool_removals), filler questions leave the banks
-- (CD-005), and the seeded superadmin name loses the word "Platform" (SA-004).
-- MySQL 8 / MariaDB 10.6+. Run ONCE, after 005. Back up first.
--   mysql -u USER -p DBNAME < 006_v08_users_archive_and_cleanup.up.sql
-- Safe to re-run: the columns are only added when missing, and each data fix only changes rows that still need it.
-- =====================================================================================================

-- 1. Users: "Delete" archives them, so their jobs, interviews and reports stay (SA-002/003)
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'archived_at');
SET @s := IF(@c = 0, 'ALTER TABLE users ADD COLUMN archived_at DATETIME NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'archived_by');
SET @s := IF(@c = 0, 'ALTER TABLE users ADD COLUMN archived_by INT NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- 1b. Applications: "Remove from job" (stage 'removed') remembers the stage to restore (A1/A2)
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'applications' AND COLUMN_NAME = 'removed_at');
SET @s := IF(@c = 0, 'ALTER TABLE applications ADD COLUMN removed_at DATETIME NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'applications' AND COLUMN_NAME = 'removed_by');
SET @s := IF(@c = 0, 'ALTER TABLE applications ADD COLUMN removed_by INT NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
SET @c := (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'applications' AND COLUMN_NAME = 'removed_stage');
SET @s := IF(@c = 0, 'ALTER TABLE applications ADD COLUMN removed_stage VARCHAR(30) NULL', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- 1c. Talent pool: people a company removed from its pool (A3). Adding them again deletes the row.
CREATE TABLE IF NOT EXISTS pool_removals (
  id INTEGER NOT NULL AUTO_INCREMENT,
  created_at DATETIME NOT NULL,
  company_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  removed_by INTEGER NULL,
  PRIMARY KEY (id),
  CONSTRAINT uq_pool_removal UNIQUE (company_id, user_id),
  FOREIGN KEY(company_id) REFERENCES companies (id),
  FOREIGN KEY(user_id) REFERENCES users (id)
);
SET @c := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pool_removals' AND INDEX_NAME = 'ix_pool_removals_company_id');
SET @s := IF(@c = 0, 'CREATE INDEX ix_pool_removals_company_id ON pool_removals (company_id)', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;
SET @c := (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'pool_removals' AND INDEX_NAME = 'ix_pool_removals_user_id');
SET @s := IF(@c = 0, 'CREATE INDEX ix_pool_removals_user_id ON pool_removals (user_id)', 'DO 0');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- The technical-retake limit ("policy.retake_max", default 5) is a setting, not a column: nothing to create.
-- New round statuses "voided" (replaced by a technical retake) and "cancelled" fit the existing status column.

-- =====================================================================================================
-- Data fixes
-- =====================================================================================================

-- 2. CD-005: generic filler questions written without Claude (by practice quizzes, skill checks and short rounds) were
--    saved to the question banks as approved. They go back to "pending" so a person reviews them before any reuse.
--    Questions people wrote, and questions Claude wrote, are not touched.
UPDATE questions SET status = 'pending'
WHERE source = 'ai' AND status = 'approved' AND (
      text LIKE 'Which statement about % is most accurate for a level % practitioner?'
   OR text LIKE 'A teammate''s % work passes review but fails in production. What should you check first?'
   OR text LIKE 'What is the main benefit of writing automated tests for % code?'
   OR text LIKE 'You must learn a new part of % quickly for a project. What works best?'
   OR text LIKE 'When is it right to choose a simpler % solution over a more powerful one?'
   OR text LIKE 'How should a % decision with real trade-offs be recorded for the team?');

-- 3. SA-004: the seeded superadmin was named "Platform Superadmin"; the word "Platform" showed next to the bell
UPDATE users SET name = 'Superadmin' WHERE is_superadmin = 1 AND name = 'Platform Superadmin';
