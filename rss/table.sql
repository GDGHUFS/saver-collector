CREATE TABLE IF NOT EXISTS news_feeds (
    id BIGSERIAL PRIMARY KEY,
    feed_url TEXT NOT NULL UNIQUE CHECK (length(btrim(feed_url)) > 0),
    publisher TEXT NOT NULL CHECK (length(btrim(publisher)) > 0),
    title TEXT NOT NULL CHECK (length(btrim(title)) > 0),
    link TEXT NOT NULL CHECK (length(btrim(link)) > 0),
    description TEXT NOT NULL,
    language TEXT,
    copyright TEXT,
    managing_editor TEXT,
    web_master TEXT,
    pub_date TIMESTAMPTZ,
    last_build_date TIMESTAMPTZ,
    generator TEXT,
    docs TEXT,
    cloud JSONB,
    ttl INTEGER CHECK (ttl IS NULL OR ttl >= 0),
    image JSONB,
    rating TEXT,
    text_input JSONB,
    skip_hours SMALLINT[] NOT NULL DEFAULT '{}',
    skip_days TEXT[] NOT NULL DEFAULT '{}',
    extensions JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS news_feed_categories (
    id BIGSERIAL PRIMARY KEY,
    feed_id BIGINT NOT NULL REFERENCES news_feeds(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(btrim(name)) > 0),
    domain TEXT
);
CREATE TABLE IF NOT EXISTS news_items (
    id BIGSERIAL PRIMARY KEY,
    feed_id BIGINT NOT NULL REFERENCES news_feeds(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    link TEXT NOT NULL,
    description TEXT,
    author TEXT,
    comments TEXT,
    enclosure_url TEXT,
    enclosure_length BIGINT CHECK (
        enclosure_length IS NULL OR enclosure_length >= 0
    ),
    enclosure_type TEXT,
    guid TEXT,
    guid_is_permalink BOOLEAN,
    pub_date TIMESTAMPTZ,
    source_name TEXT,
    source_url TEXT,
    extensions JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (length(btrim(title)) > 0),
    CHECK (length(btrim(link)) > 0)
);
CREATE TABLE IF NOT EXISTS news_item_categories (
    id BIGSERIAL PRIMARY KEY,
    item_id BIGINT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(btrim(name)) > 0),
    domain TEXT
);
CREATE INDEX IF NOT EXISTS news_items_latest_idx
    ON news_items (pub_date DESC NULLS LAST, id DESC);
CREATE INDEX IF NOT EXISTS news_feeds_publisher_idx
    ON news_feeds (publisher);
CREATE UNIQUE INDEX IF NOT EXISTS news_items_feed_guid_idx
    ON news_items (feed_id, guid)
    WHERE guid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS news_items_feed_link_idx
    ON news_items (feed_id, link)
    WHERE guid IS NULL AND link IS NOT NULL;
