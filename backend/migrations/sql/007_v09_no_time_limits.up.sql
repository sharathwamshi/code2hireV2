-- =====================================================================================================
-- Code2Hire V02.00.09 · migration 007: no time limits on joining (N5).
-- No new tables or columns. Data only:
--   1. Open round invites lose their deadline (rounds now have no deadline unless the company sets
--      round.deadline_days). Invites that already expired are not reopened: use "Interview again" -> Re-send.
--   2. Unused, still-valid candidate portal links stop expiring: they now work until the candidate sets up their
--      account, or until the team cancels them.
-- MySQL 8 / MariaDB 10.6+. Run ONCE, after 006. Back up first.
--   mysql -u USER -p DBNAME < 007_v09_no_time_limits.up.sql
-- Safe to re-run.
-- =====================================================================================================

-- 1. Open invites: no deadline
UPDATE round_attempts SET deadline_at = NULL
 WHERE status IN ('invited', 'scheduled') AND deadline_at IS NOT NULL;

-- 2. Unused portal links that haven't expired yet: valid until used (2099-12-31 means "no time limit")
UPDATE invite_links SET expires_at = '2099-12-31 00:00:00'
 WHERE used_at IS NULL AND revoked = 0 AND expires_at > UTC_TIMESTAMP();
