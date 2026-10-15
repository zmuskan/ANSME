ALTER TABLE analyses
    ADD COLUMN IF NOT EXISTS price_raw TEXT,
    ADD COLUMN IF NOT EXISTS price_currency VARCHAR(16);

ALTER TABLE price_history
    ADD COLUMN IF NOT EXISTS price_raw TEXT,
    ADD COLUMN IF NOT EXISTS price_currency VARCHAR(16);
