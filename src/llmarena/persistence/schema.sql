CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    left_provider TEXT NOT NULL,
    left_model TEXT NOT NULL,
    left_display TEXT NOT NULL,
    right_provider TEXT NOT NULL,
    right_model TEXT NOT NULL,
    right_display TEXT NOT NULL,
    winner TEXT,
    score_left INTEGER NOT NULL DEFAULT 0,
    score_right INTEGER NOT NULL DEFAULT 0,
    rules_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches(id),
    round_no INTEGER NOT NULL,
    winner TEXT NOT NULL,
    reason TEXT NOT NULL,
    hp_left INTEGER NOT NULL,
    hp_right INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS golpes (
    id INTEGER PRIMARY KEY,
    match_id TEXT NOT NULL REFERENCES matches(id),
    round_no INTEGER NOT NULL,
    challenge_seq INTEGER NOT NULL,
    side TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    challenge_id TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    category TEXT NOT NULL,
    passed INTEGER NOT NULL,
    late INTEGER NOT NULL DEFAULT 0,
    counter INTEGER NOT NULL DEFAULT 0,
    damage INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    output_chars INTEGER NOT NULL DEFAULT 0,
    code TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS golpes_model ON golpes(provider, model);
CREATE INDEX IF NOT EXISTS golpes_match ON golpes(match_id);
CREATE VIEW IF NOT EXISTS match_sides AS
    SELECT id AS match_id, 'left' AS side, left_provider AS provider, left_model AS model, left_display AS display_name,
           winner, CASE WHEN winner = 'left' THEN 1 ELSE 0 END AS won,
           CASE WHEN winner = 'right' THEN 1 ELSE 0 END AS lost, CASE WHEN winner = 'draw' THEN 1 ELSE 0 END AS drew
    FROM matches
    UNION ALL
    SELECT id, 'right', right_provider, right_model, right_display,
           winner, CASE WHEN winner = 'right' THEN 1 ELSE 0 END,
           CASE WHEN winner = 'left' THEN 1 ELSE 0 END, CASE WHEN winner = 'draw' THEN 1 ELSE 0 END
    FROM matches;
CREATE TABLE IF NOT EXISTS generated_challenges (
    id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    level INTEGER NOT NULL,
    statement_src TEXT NOT NULL,
    challenge_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
