-- 기상청 단기예보는 격자 단위로 제공된다. 여러 행정구역이 같은 격자를
-- 공유하므로 위치 기준정보와 예보 데이터를 격자 테이블로 연결한다.
CREATE TABLE IF NOT EXISTS weather_grid_points (
    nx SMALLINT NOT NULL CHECK (nx BETWEEN 1 AND 149),
    ny SMALLINT NOT NULL CHECK (ny BETWEEN 1 AND 253),
    longitude DOUBLE PRECISION NOT NULL
        CHECK (longitude BETWEEN 120 AND 140),
    latitude DOUBLE PRECISION NOT NULL
        CHECK (latitude BETWEEN 30 AND 45),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (nx, ny)
);

-- 재시도와 페이지 호출을 포함한 실제 요청 횟수를 KST 날짜별로 제한한다.
CREATE TABLE IF NOT EXISTS weather_api_daily_usage (
    usage_date DATE PRIMARY KEY,
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weather_locations (
    administrative_code TEXT PRIMARY KEY
        CHECK (administrative_code ~ '^[0-9]{10}$'),
    region_level_1 TEXT NOT NULL
        CHECK (length(btrim(region_level_1)) > 0),
    region_level_2 TEXT
        CHECK (region_level_2 IS NULL OR length(btrim(region_level_2)) > 0),
    region_level_3 TEXT
        CHECK (region_level_3 IS NULL OR length(btrim(region_level_3)) > 0),
    nx SMALLINT NOT NULL,
    ny SMALLINT NOT NULL,
    longitude DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    source_updated_on DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (nx, ny) REFERENCES weather_grid_points (nx, ny),
    CHECK (region_level_3 IS NULL OR region_level_2 IS NOT NULL),
    CHECK ((longitude IS NULL) = (latitude IS NULL)),
    CHECK (longitude IS NULL OR longitude BETWEEN 120 AND 140),
    CHECK (latitude IS NULL OR latitude BETWEEN 30 AND 45)
);

-- 하나의 발표본은 한 격자와 기상청 발표시각의 조합으로 식별한다.
-- 같은 발표본을 다시 수집하면 새 행을 만들지 않고 최신 값으로 갱신한다.
CREATE TABLE IF NOT EXISTS weather_forecast_issues (
    id BIGSERIAL PRIMARY KEY,
    nx SMALLINT NOT NULL,
    ny SMALLINT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (nx, ny) REFERENCES weather_grid_points (nx, ny),
    UNIQUE (nx, ny, issued_at)
);

-- API의 장형 category 응답을 화면 조회에 적합한 예보시각별 한 행으로 묶는다.
-- 값은 수치뿐 아니라 강수없음, 범위, 장기 구간 정성 코드도 제공되므로
-- 원문 의미를 잃지 않도록 문자열로 저장한다.
CREATE TABLE IF NOT EXISTS weather_forecasts (
    forecast_issue_id BIGINT NOT NULL
        REFERENCES weather_forecast_issues (id) ON DELETE CASCADE,
    forecast_at TIMESTAMPTZ NOT NULL,
    precipitation_probability TEXT,
    precipitation_type TEXT,
    precipitation_amount TEXT,
    humidity TEXT,
    snowfall_amount TEXT,
    sky_status TEXT,
    temperature TEXT,
    minimum_temperature TEXT,
    maximum_temperature TEXT,
    wind_u_component TEXT,
    wind_v_component TEXT,
    wave_height TEXT,
    wind_direction TEXT,
    wind_speed TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (forecast_issue_id, forecast_at),
    CHECK (
        num_nonnulls(
            precipitation_probability,
            precipitation_type,
            precipitation_amount,
            humidity,
            snowfall_amount,
            sky_status,
            temperature,
            minimum_temperature,
            maximum_temperature,
            wind_u_component,
            wind_v_component,
            wave_height,
            wind_direction,
            wind_speed
        ) > 0
    ),
    CHECK (
        num_nonnulls(
            precipitation_probability,
            precipitation_type,
            precipitation_amount,
            humidity,
            snowfall_amount,
            sky_status,
            temperature,
            minimum_temperature,
            maximum_temperature,
            wind_u_component,
            wind_v_component,
            wave_height,
            wind_direction,
            wind_speed
        ) = num_nonnulls(
            NULLIF(btrim(precipitation_probability), ''),
            NULLIF(btrim(precipitation_type), ''),
            NULLIF(btrim(precipitation_amount), ''),
            NULLIF(btrim(humidity), ''),
            NULLIF(btrim(snowfall_amount), ''),
            NULLIF(btrim(sky_status), ''),
            NULLIF(btrim(temperature), ''),
            NULLIF(btrim(minimum_temperature), ''),
            NULLIF(btrim(maximum_temperature), ''),
            NULLIF(btrim(wind_u_component), ''),
            NULLIF(btrim(wind_v_component), ''),
            NULLIF(btrim(wave_height), ''),
            NULLIF(btrim(wind_direction), ''),
            NULLIF(btrim(wind_speed), '')
        )
    )
);

CREATE INDEX IF NOT EXISTS weather_locations_region_names_idx
    ON weather_locations (
        region_level_1,
        region_level_2,
        region_level_3,
        administrative_code
    );

CREATE INDEX IF NOT EXISTS weather_locations_region_level_2_idx
    ON weather_locations (region_level_2, administrative_code)
    WHERE region_level_2 IS NOT NULL;

CREATE INDEX IF NOT EXISTS weather_locations_region_level_3_idx
    ON weather_locations (region_level_3, administrative_code)
    WHERE region_level_3 IS NOT NULL;

CREATE INDEX IF NOT EXISTS weather_locations_grid_idx
    ON weather_locations (nx, ny, administrative_code);

CREATE INDEX IF NOT EXISTS weather_forecast_issues_issued_at_idx
    ON weather_forecast_issues (issued_at);
