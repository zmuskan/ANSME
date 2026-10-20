CREATE TABLE IF NOT EXISTS user_preferences (
    user_id UUID PRIMARY KEY,
    share_to_leaderboard BOOLEAN NOT NULL DEFAULT FALSE
);
