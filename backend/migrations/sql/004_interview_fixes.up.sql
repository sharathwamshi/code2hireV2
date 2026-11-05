-- =====================================================================================================
-- Code2Hire V02.00.04 · migration 004: interview bug fixes (BUG-001 to 007) and interview videos (NEW-001)
-- MySQL 8 / MariaDB 10.6+. Run ONCE, after 003. Back up first.
--   mysql -u USER -p DBNAME < 004_interview_fixes.up.sql
-- Safe to re-run: the table uses IF NOT EXISTS and each data fix only changes rows that still need it.
-- =====================================================================================================

-- 1. Interview videos: one row per continuous piece of video from one side (NEW-001)
CREATE TABLE IF NOT EXISTS recordings (
    id          INT          NOT NULL AUTO_INCREMENT,
    created_at  DATETIME     NOT NULL,
    attempt_id  INT          NOT NULL,
    side        VARCHAR(20)  NOT NULL,
    segment     VARCHAR(40)  NOT NULL,
    mime        VARCHAR(60)  NULL,
    started_at  DATETIME     NULL,
    last_at     DATETIME     NULL,
    seconds     FLOAT        NULL,
    bytes       BIGINT       NULL,
    next_seq    INT          NULL,
    status      VARCHAR(20)  NULL,
    raw_key     VARCHAR(255) NULL,
    file_key    VARCHAR(255) NULL,
    storage     VARCHAR(20)  NULL,
    note        VARCHAR(255) NULL,
    deleted_at  DATETIME     NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_recording_segment (attempt_id, segment),
    KEY ix_recordings_attempt_id (attempt_id),
    CONSTRAINT fk_recordings_attempt FOREIGN KEY (attempt_id) REFERENCES round_attempts (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- =====================================================================================================
-- Data fixes
-- =====================================================================================================

-- 2. Recordings made before this release (one file per call, kept in round_attempts.result.recording) become rows,
--    so they play in the new video player. The files stay where they are (UPLOAD_DIR/recordings).
INSERT INTO recordings (created_at, attempt_id, side, segment, mime, started_at, last_at, seconds, bytes, next_seq, status,
                        file_key, storage, note)
SELECT COALESCE(ra.completed_at, ra.created_at), ra.id, 'interviewer', CONCAT('legacy', jt.n - 1), 'video/webm',
       ra.started_at, COALESCE(ra.completed_at, ra.started_at), jt.secs, jt.size, 1, 'ready', jt.file, 'local',
       'Recorded before V02.00.04'
  FROM round_attempts ra,
       JSON_TABLE(ra.result, '$.recording[*]' COLUMNS (n FOR ORDINALITY, file VARCHAR(255) PATH '$.file',
                                                       secs DOUBLE PATH '$.seconds', size BIGINT PATH '$.bytes')) jt
 WHERE JSON_LENGTH(JSON_EXTRACT(ra.result, '$.recording')) > 0
   AND NOT EXISTS (SELECT 1 FROM recordings r WHERE r.attempt_id = ra.id AND r.segment = CONCAT('legacy', jt.n - 1));

-- 3. Number settings saved outside their limits before this release (BUG-006, BUG-007: "-5", "99999")
--    are brought inside the limits. A value that isn't a number is removed, so the level above applies again.
DELETE FROM settings
 WHERE `key` IN ('voice.silence_seconds','mcq.questions','mcq.minutes','interview.questions','interview.followup_depth',
                 'interview.minutes','interview.attempts','pass.advance','pass.reject','integrity.warnings_allowed',
                 'isha.options','f2f.questions','call.join_early_minutes','report.auto_share_days','policy.reinterview_max',
                 'policy.decision_sla_hours','retention.days','recording.retention_days','invite.link_days',
                 'cert.validity_months','cert.cooldown_days')
   AND JSON_UNQUOTE(value) NOT REGEXP '^-?[0-9]+(\\.0+)?$';
UPDATE settings SET value = '2' WHERE `key` = 'voice.silence_seconds' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 2;
UPDATE settings SET value = '30' WHERE `key` = 'voice.silence_seconds' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 30;
UPDATE settings SET value = '1' WHERE `key` = 'mcq.questions' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '100' WHERE `key` = 'mcq.questions' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 100;
UPDATE settings SET value = '1' WHERE `key` = 'mcq.minutes' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '240' WHERE `key` = 'mcq.minutes' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 240;
UPDATE settings SET value = '1' WHERE `key` = 'interview.questions' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '20' WHERE `key` = 'interview.questions' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 20;
UPDATE settings SET value = '0' WHERE `key` = 'interview.followup_depth' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '5' WHERE `key` = 'interview.followup_depth' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 5;
UPDATE settings SET value = '5' WHERE `key` = 'interview.minutes' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 5;
UPDATE settings SET value = '180' WHERE `key` = 'interview.minutes' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 180;
UPDATE settings SET value = '1' WHERE `key` = 'interview.attempts' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '5' WHERE `key` = 'interview.attempts' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 5;
UPDATE settings SET value = '0' WHERE `key` = 'pass.advance' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '100' WHERE `key` = 'pass.advance' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 100;
UPDATE settings SET value = '0' WHERE `key` = 'pass.reject' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '100' WHERE `key` = 'pass.reject' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 100;
UPDATE settings SET value = '0' WHERE `key` = 'integrity.warnings_allowed' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '20' WHERE `key` = 'integrity.warnings_allowed' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 20;
UPDATE settings SET value = '2' WHERE `key` = 'isha.options' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 2;
UPDATE settings SET value = '6' WHERE `key` = 'isha.options' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 6;
UPDATE settings SET value = '1' WHERE `key` = 'f2f.questions' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '30' WHERE `key` = 'f2f.questions' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 30;
UPDATE settings SET value = '0' WHERE `key` = 'call.join_early_minutes' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '120' WHERE `key` = 'call.join_early_minutes' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 120;
UPDATE settings SET value = '0' WHERE `key` = 'report.auto_share_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '90' WHERE `key` = 'report.auto_share_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 90;
UPDATE settings SET value = '0' WHERE `key` = 'policy.reinterview_max' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '5' WHERE `key` = 'policy.reinterview_max' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 5;
UPDATE settings SET value = '1' WHERE `key` = 'policy.decision_sla_hours' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '720' WHERE `key` = 'policy.decision_sla_hours' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 720;
UPDATE settings SET value = '30' WHERE `key` = 'retention.days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 30;
UPDATE settings SET value = '3650' WHERE `key` = 'retention.days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 3650;
UPDATE settings SET value = '30' WHERE `key` = 'recording.retention_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 30;
UPDATE settings SET value = '730' WHERE `key` = 'recording.retention_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 730;
UPDATE settings SET value = '1' WHERE `key` = 'invite.link_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '90' WHERE `key` = 'invite.link_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 90;
UPDATE settings SET value = '1' WHERE `key` = 'cert.validity_months' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 1;
UPDATE settings SET value = '60' WHERE `key` = 'cert.validity_months' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 60;
UPDATE settings SET value = '0' WHERE `key` = 'cert.cooldown_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) < 0;
UPDATE settings SET value = '365' WHERE `key` = 'cert.cooldown_days' AND CAST(JSON_UNQUOTE(value) AS DECIMAL(20, 0)) > 365;
-- Limits inside a job's own round settings (jobs.rounds) are applied when they are read, and checked when the job is saved.

-- 4. "Record the call" is no longer a switch: every interview is recorded (NEW-001)
DELETE FROM settings WHERE `key` = 'call.record';

-- 5. Question bank: copies with the same text are archived, keeping the newest of each (BUG-004).
--    Archived questions stay in old reports (each test keeps its own copy of the questions it used).
UPDATE questions q
  JOIN (SELECT COALESCE(company_id, 0) AS cid, LOWER(TRIM(text)) AS t, MAX(id) AS keep_id
          FROM questions WHERE status <> 'archived'
         GROUP BY COALESCE(company_id, 0), LOWER(TRIM(text)) HAVING COUNT(*) > 1) d
    ON d.cid = COALESCE(q.company_id, 0) AND d.t = LOWER(TRIM(q.text))
   SET q.status = 'archived'
 WHERE q.status <> 'archived' AND q.id <> d.keep_id;
