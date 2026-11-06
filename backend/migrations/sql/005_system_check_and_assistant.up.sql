-- =====================================================================================================
-- Code2Hire V02.00.05 · migration 005: system check before interviews, and "Ask Hira" for hiring teams
-- MySQL 8 / MariaDB 10.6+. Run ONCE, after 004. Back up first.
--   mysql -u USER -p DBNAME < 005_system_check_and_assistant.up.sql
-- Safe to re-run: every statement uses IF NOT EXISTS. No existing rows are changed.
-- =====================================================================================================

-- 1. One row per run of the system check (before a round, a re-check on rejoin, "Test my setup",
--    or an "I need help" request). attempt_id is empty for "Test my setup".
CREATE TABLE IF NOT EXISTS system_checks (
    id          INT          NOT NULL AUTO_INCREMENT,
    created_at  DATETIME     NOT NULL,
    attempt_id  INT          NULL,
    user_id     INT          NOT NULL,
    role        VARCHAR(20)  NOT NULL,
    mode        VARCHAR(20)  NULL,
    passed      TINYINT(1)   NOT NULL,
    steps       JSON         NULL,
    device      JSON         NULL,
    user_agent  VARCHAR(400) NULL,
    help_step   VARCHAR(30)  NULL,
    help_note   VARCHAR(500) NULL,
    PRIMARY KEY (id),
    KEY ix_system_checks_attempt_id (attempt_id),
    KEY ix_system_checks_user_id (user_id),
    CONSTRAINT fk_system_checks_attempt FOREIGN KEY (attempt_id) REFERENCES round_attempts (id),
    CONSTRAINT fk_system_checks_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. The "Ask Hira" chat: questions and answers, kept per person (the newest 200).
CREATE TABLE IF NOT EXISTS assistant_messages (
    id          INT          NOT NULL AUTO_INCREMENT,
    created_at  DATETIME     NOT NULL,
    user_id     INT          NOT NULL,
    company_id  INT          NULL,
    role        VARCHAR(10)  NOT NULL,
    text        TEXT         NOT NULL,
    intent      VARCHAR(40)  NULL,
    data        JSON         NULL,
    PRIMARY KEY (id),
    KEY ix_assistant_messages_user_id (user_id),
    KEY ix_assistant_messages_company_id (company_id),
    CONSTRAINT fk_assistant_messages_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- No data changes. After this release:
--  * Candidates run the system check and tick "I've read the instructions" before a real round can start.
--    A round that was already running asks only for a short device re-check the next time it is opened.
--  * Applications added by picking an existing candidate from the dropdown have source = 'picked'.
--  * The new company / job / round setting "instructions.extra" lives in the existing settings table.
