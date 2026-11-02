-- Rollback 001 · removes call signalling history (chat and captions sent during calls).
DROP TABLE IF EXISTS call_signals;
