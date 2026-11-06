-- Code2Hire V02.00.05 · migration 005 rollback. Removes the system check history and the "Ask Hira" chat history.
-- Run before going back to V02.00.04 code. Applications with source = 'picked' stay (V02.00.04 shows them as added).
DROP TABLE IF EXISTS assistant_messages;
DROP TABLE IF EXISTS system_checks;
