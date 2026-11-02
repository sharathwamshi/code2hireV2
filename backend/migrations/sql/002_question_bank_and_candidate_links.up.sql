-- =====================================================================================
-- Code2Hire migration 002 · Question bank folders and versions,
--                           candidates added by the hiring team, personal portal links   (2026-10-29)
-- Target: MySQL 8 / MariaDB 10.6+        Run BEFORE starting the new code.
-- Requires migration 001.                Run once (the ALTERs are not repeatable).
-- =====================================================================================

-- 1. Question bank folders (nested by parent_id; company_id NULL = global Code2Hire bank)
CREATE TABLE IF NOT EXISTS question_folders (
    id           INT           NOT NULL AUTO_INCREMENT,
    created_at   DATETIME      NOT NULL,
    company_id   INT           NULL,
    parent_id    INT           NULL,
    name         VARCHAR(120)  NOT NULL,
    description  VARCHAR(255)  NULL,
    created_by   INT           NULL,
    PRIMARY KEY (id),
    KEY ix_question_folders_company_id (company_id),
    KEY ix_question_folders_parent_id (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. New columns on questions
ALTER TABLE questions
    ADD COLUMN folder_id     INT       NULL AFTER company_id,
    ADD COLUMN version       INT       NULL AFTER folder_id,
    ADD COLUMN tags          JSON      NULL AFTER version,
    ADD COLUMN time_seconds  INT       NULL AFTER tags,
    ADD COLUMN updated_by    INT       NULL,
    ADD COLUMN updated_at    DATETIME  NULL,
    ADD KEY ix_questions_folder_id (folder_id);

-- 3. Version history of every question
CREATE TABLE IF NOT EXISTS question_versions (
    id           INT           NOT NULL AUTO_INCREMENT,
    created_at   DATETIME      NOT NULL,
    question_id  INT           NOT NULL,
    version      INT           NOT NULL,
    snapshot     JSON          NULL COMMENT 'text, code, options, answer, explanation, skill, level, tags, time_seconds',
    note         VARCHAR(255)  NULL,
    changed_by   INT           NULL,
    PRIMARY KEY (id),
    KEY ix_question_versions_question_id (question_id),
    CONSTRAINT fk_question_versions_question FOREIGN KEY (question_id) REFERENCES questions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Candidates added by a company's hiring team
ALTER TABLE candidate_profiles
    ADD COLUMN source_company_id  INT  NULL,
    ADD COLUMN added_by           INT  NULL,
    ADD KEY ix_candidate_profiles_source_company_id (source_company_id);

-- 5. Personal portal links (only a SHA-256 hash of the token is stored)
CREATE TABLE IF NOT EXISTS invite_links (
    id          INT          NOT NULL AUTO_INCREMENT,
    created_at  DATETIME     NOT NULL,
    token_hash  VARCHAR(64)  NOT NULL,
    user_id     INT          NOT NULL,
    company_id  INT          NULL,
    job_id      INT          NULL,
    purpose     VARCHAR(20)  NULL COMMENT 'candidate | staff',
    created_by  INT          NULL,
    expires_at  DATETIME     NOT NULL,
    opened_at   DATETIME     NULL,
    used_at     DATETIME     NULL COMMENT 'password set; link stops working',
    revoked     TINYINT(1)   NULL,
    PRIMARY KEY (id),
    UNIQUE KEY ix_invite_links_token_hash (token_hash),
    KEY ix_invite_links_user_id (user_id),
    KEY ix_invite_links_company_id (company_id),
    CONSTRAINT fk_invite_links_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. Data: every existing question becomes version 1 with a history entry
UPDATE questions SET version = 1          WHERE version IS NULL;
UPDATE questions SET tags = JSON_ARRAY()  WHERE tags IS NULL;
UPDATE questions SET updated_at = created_at WHERE updated_at IS NULL;

INSERT INTO question_versions (created_at, question_id, version, snapshot, note, changed_by)
SELECT NOW(), q.id, 1,
       JSON_OBJECT('text', q.text, 'code', q.code, 'options', q.options, 'answer', q.answer,
                   'explanation', q.explanation, 'skill', q.skill, 'level', q.level,
                   'tags', JSON_ARRAY(), 'time_seconds', NULL),
       'Original (before versioning)', NULL
FROM questions q
WHERE NOT EXISTS (SELECT 1 FROM question_versions v WHERE v.question_id = q.id);

-- No other data changes:
--   * The new permission `candidates.add` and the settings mcq.folder_ids, invite.link_days and
--     invite.require_password are defined in code; existing roles and companies pick them up.
--   * Candidates added before this release have no link yet; staff can send one with
--     "Get link again" on Added candidates or the Talent pool.
