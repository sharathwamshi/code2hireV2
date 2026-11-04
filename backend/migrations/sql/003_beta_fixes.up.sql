-- =====================================================================================================
-- Code2Hire V02.00.03 · migration 003: beta bug fixes (BETACODE2-1 to 48)
-- MySQL 8 / MariaDB 10.6+. Run ONCE, after 001 and 002. Back up first.
--   mysql -u USER -p DBNAME < 003_beta_fixes.up.sql
-- Re-running stops at the first ALTER with "Duplicate column": harmless, it means it's already applied.
-- =====================================================================================================

-- 1. Sign-in throttle: failed attempts per email / IP address, shared by every server worker (BETACODE2-2)
CREATE TABLE IF NOT EXISTS login_throttles (
    id            INT          NOT NULL AUTO_INCREMENT,
    created_at    DATETIME     NOT NULL,
    `key`         VARCHAR(190) NOT NULL,
    failures      INT          NOT NULL DEFAULT 0,
    window_start  DATETIME     NULL,
    locked_until  DATETIME     NULL,
    PRIMARY KEY (id),
    UNIQUE KEY ix_login_throttles_key (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Personal links: "Sent" only after the team copied or sent the link (BETACODE2-37, -38, -47)
ALTER TABLE invite_links
    ADD COLUMN shared_at   DATETIME    NULL,
    ADD COLUMN shared_via  VARCHAR(20) NULL;

-- 3. Disputes: status, the reviewer's answer, who and when (BETACODE2-31)
ALTER TABLE reports
    ADD COLUMN disputed_at          DATETIME    NULL,
    ADD COLUMN dispute_status       VARCHAR(20) NULL,
    ADD COLUMN dispute_resolution   TEXT        NULL,
    ADD COLUMN dispute_resolved_by  INT         NULL,
    ADD COLUMN dispute_resolved_at  DATETIME    NULL;

-- 4. Hiring templates: edit history and archive (BETACODE2-26)
ALTER TABLE hiring_templates
    ADD COLUMN updated_by  INT        NULL,
    ADD COLUMN updated_at  DATETIME   NULL,
    ADD COLUMN archived    TINYINT(1) NULL;

-- =====================================================================================================
-- Data fixes
-- =====================================================================================================

-- templates: not archived; last change = creation
UPDATE hiring_templates SET archived = 0 WHERE archived IS NULL;
UPDATE hiring_templates SET updated_at = created_at WHERE updated_at IS NULL;

-- open disputes raised before this release
UPDATE reports SET dispute_status = 'open', disputed_at = created_at
 WHERE disputed = 1 AND dispute_status IS NULL;

-- links created before this release were shown as "Link sent", so keep them as sent
UPDATE invite_links SET shared_at = created_at, shared_via = 'manual'
 WHERE shared_at IS NULL AND revoked = 0;

-- jobs: hires needed is at least 1 (BETACODE2-18, -28: "0 / -5" in the jobs list)
UPDATE jobs SET hires_target = 1 WHERE hires_target IS NULL OR hires_target < 1;
-- jobs: no negative salaries; swap bands saved upside down (min above max)
UPDATE jobs SET salary_min = NULL WHERE salary_min < 0;
UPDATE jobs SET salary_max = NULL WHERE salary_max < 0;
UPDATE jobs SET salary_min = (@tmp := salary_min), salary_min = salary_max, salary_max = @tmp
 WHERE salary_min IS NOT NULL AND salary_max IS NOT NULL AND salary_min > salary_max;

-- rounds: only one live invite per candidate per round (BETACODE2-7). Duplicates become 'cancelled':
-- (a) an invite next to a round that's already running
UPDATE round_attempts ra
  JOIN (SELECT DISTINCT application_id, round_index FROM round_attempts
         WHERE status IN ('in_progress', 'paused') AND application_id IS NOT NULL) run
    ON run.application_id = ra.application_id AND run.round_index = ra.round_index
   SET ra.status = 'cancelled'
 WHERE ra.status IN ('invited', 'scheduled');
-- (b) several invites for the same round: keep the newest
UPDATE round_attempts ra
  JOIN (SELECT application_id, round_index, MAX(id) AS keep_id FROM round_attempts
         WHERE status IN ('invited', 'scheduled') AND application_id IS NOT NULL
         GROUP BY application_id, round_index HAVING COUNT(*) > 1) d
    ON d.application_id = ra.application_id AND d.round_index = ra.round_index
   SET ra.status = 'cancelled'
 WHERE ra.status IN ('invited', 'scheduled') AND ra.id < d.keep_id;

-- Accounts with an email that can't receive mail (BETACODE2-1). NOT changed automatically; list them and decide:
--   SELECT id, email, kind, created_at FROM users
--    WHERE email NOT REGEXP '^[^@[:space:]]+@([A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\\.)+[A-Za-z]{2,24}$';
