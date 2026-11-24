DELETE FROM question_versions WHERE question_id IN (SELECT id FROM questions WHERE kind = 'interview');
DELETE FROM questions WHERE kind = 'interview';
DROP INDEX ix_questions_kind ON questions;
ALTER TABLE questions DROP COLUMN kind;
ALTER TABLE questions DROP COLUMN meta;
