-- Manager-initiated multi-bot delete confirmation cards.
CREATE TABLE IF NOT EXISTS bot_delete_requests (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL DEFAULT '',
  bots_json TEXT NOT NULL DEFAULT '[]',
  state TEXT NOT NULL DEFAULT 'pending',
  message_id TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_bot_delete_requests_bot_state
  ON bot_delete_requests(bot, state, created_at);
