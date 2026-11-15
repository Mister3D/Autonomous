-- Per-bot notebook: standing orders, unfinished lines, and notes.
-- Survives chat compaction. Not shared with other bots.
CREATE TABLE IF NOT EXISTS bot_notebook (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bot_notebook_bot_kind
  ON bot_notebook(bot, kind, updated_at);
