-- Daily token usage per bot (survives chat clear; removed with the bot).
CREATE TABLE IF NOT EXISTS bot_token_usage_daily (
  bot TEXT NOT NULL,
  day TEXT NOT NULL,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bot, day),
  FOREIGN KEY (bot) REFERENCES bots(name) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bot_token_usage_daily_day
  ON bot_token_usage_daily(day);
