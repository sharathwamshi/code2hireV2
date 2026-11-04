-- OPTIONAL, run at most ONCE, right after migration 003 and only if it applies to you (BETACODE2-6).
-- Before V02.00.03, "When" times were saved as the interviewer's local clock time without a timezone.
-- If all your interviewers schedule in India (IST, UTC+05:30), this converts the interviews that are still
-- upcoming to UTC, which is how V02.00.03 stores every time. Change 330 (minutes) for another timezone.
UPDATE round_attempts
   SET scheduled_at = DATE_SUB(scheduled_at, INTERVAL 330 MINUTE)
 WHERE scheduled_at IS NOT NULL
   AND status IN ('invited', 'scheduled');
