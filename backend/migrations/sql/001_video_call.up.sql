-- =====================================================================================
-- Code2Hire migration 001 · Built-in video call for F2F rounds            (2026-10-24)
-- Target: MySQL 8 / MariaDB 10.6+        Run BEFORE starting the new code.
-- Skip this file if your database already has the `call_signals` table.
-- =====================================================================================

CREATE TABLE IF NOT EXISTS call_signals (
    id          INT          NOT NULL AUTO_INCREMENT,
    created_at  DATETIME     NOT NULL,
    attempt_id  INT          NOT NULL,
    sender      VARCHAR(20)  NOT NULL COMMENT 'candidate | interviewer',
    kind        VARCHAR(20)  NOT NULL COMMENT 'join | ready | offer | answer | ice | bye | chat | caption | focus | media',
    payload     JSON         NULL,
    PRIMARY KEY (id),
    KEY ix_call_signals_attempt_id (attempt_id),
    CONSTRAINT fk_call_signals_attempt FOREIGN KEY (attempt_id) REFERENCES round_attempts (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- No data changes. New settings (call.*) live in code and inherit automatically.
