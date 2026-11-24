-- V02.01.05 rollback
DROP INDEX IF EXISTS ix_questions_job_id ON questions;
ALTER TABLE questions DROP COLUMN IF EXISTS job_id;
