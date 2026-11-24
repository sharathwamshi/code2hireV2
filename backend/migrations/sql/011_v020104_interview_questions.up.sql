-- V02.01.04: the question bank also keeps interview questions (Alembic 0012 does the same; use one or the other)
ALTER TABLE questions ADD COLUMN kind VARCHAR(20) NOT NULL DEFAULT 'mcq';
CREATE INDEX ix_questions_kind ON questions (kind);
ALTER TABLE questions ADD COLUMN meta JSON NULL;
