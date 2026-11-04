-- Rolls back migration 003. Data fixes (hires, salary bands, cancelled duplicate invites) are not undone.
ALTER TABLE hiring_templates DROP COLUMN archived, DROP COLUMN updated_at, DROP COLUMN updated_by;
ALTER TABLE reports DROP COLUMN dispute_resolved_at, DROP COLUMN dispute_resolved_by, DROP COLUMN dispute_resolution,
                    DROP COLUMN dispute_status, DROP COLUMN disputed_at;
ALTER TABLE invite_links DROP COLUMN shared_via, DROP COLUMN shared_at;
DROP TABLE IF EXISTS login_throttles;
