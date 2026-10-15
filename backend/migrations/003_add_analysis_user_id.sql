BEGIN;

ALTER TABLE analyses
    ADD COLUMN IF NOT EXISTS user_id UUID;

CREATE INDEX IF NOT EXISTS ix_analyses_user_id
    ON analyses (user_id);

COMMIT;
