-- V02.01.05: a job's own set of interview questions (same as Alembic 0013_v020105_job_question_sets)
ALTER TABLE questions ADD COLUMN IF NOT EXISTS job_id INT NULL;
CREATE INDEX IF NOT EXISTS ix_questions_job_id ON questions (job_id);
