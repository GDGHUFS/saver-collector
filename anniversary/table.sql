CREATE TABLE IF NOT EXISTS anniversary_special_days (
    id BIGSERIAL PRIMARY KEY,
    observed_date DATE NOT NULL,
    date_kind TEXT NOT NULL CHECK (date_kind IN ('01', '02', '03', '04')),
    date_name TEXT NOT NULL CHECK (length(btrim(date_name)) > 0),
    is_holiday BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS anniversary_special_days_unique_key
    ON anniversary_special_days (observed_date, date_kind, date_name);

CREATE INDEX IF NOT EXISTS anniversary_special_days_date_idx
    ON anniversary_special_days (observed_date, id);

CREATE INDEX IF NOT EXISTS anniversary_special_days_holiday_idx
    ON anniversary_special_days (observed_date, id)
    WHERE is_holiday = TRUE;
