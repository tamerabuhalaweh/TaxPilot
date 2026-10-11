-- 0003: session-bound CSRF tokens (Sprint 1 P0-C). Immutable history: never edit 0001/0002.
ALTER TABLE user_sessions ADD COLUMN IF NOT EXISTS csrf_hash TEXT;
