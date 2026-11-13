-- Code2Hire V02.00.09 · undo migration 007 (best effort: the old deadlines aren't stored, so open invites get 5 days
-- from now and unused portal links 7 days from now, which were the V08 defaults).
UPDATE round_attempts SET deadline_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL 5 DAY)
 WHERE status IN ('invited', 'scheduled') AND deadline_at IS NULL AND practice_user_id IS NULL;
UPDATE invite_links SET expires_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL 7 DAY)
 WHERE used_at IS NULL AND revoked = 0 AND expires_at >= '2099-12-31 00:00:00';
