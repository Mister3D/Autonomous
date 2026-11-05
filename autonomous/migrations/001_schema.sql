-- Autonomous schema (squashed). Fresh installs apply this once as version 1.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bots (
  id TEXT,
  name TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  capability TEXT NOT NULL DEFAULT 'none',
  internet INTEGER NOT NULL DEFAULT 1,
  auto_sleep INTEGER NOT NULL DEFAULT 1,
  desk_last_active_at TEXT,
  allow_host_shell INTEGER NOT NULL DEFAULT 0,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'idle',
  guard_json TEXT NOT NULL DEFAULT '{}',
  desk_json TEXT,
  model TEXT NOT NULL DEFAULT '',
  pi_session_id TEXT NOT NULL DEFAULT '',
  memory_access INTEGER NOT NULL DEFAULT 1,
  avatar TEXT NOT NULL DEFAULT '',
  avatar_color INTEGER NOT NULL DEFAULT 0,
  is_manager INTEGER NOT NULL DEFAULT 0,
  companion_id TEXT,
  companion_egress INTEGER NOT NULL DEFAULT 0,
  companion_killswitch INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bots_id ON bots(id);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  conversation_id TEXT NOT NULL DEFAULT 'main',
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  attachments_json TEXT NOT NULL DEFAULT '[]',
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (bot) REFERENCES bots(name) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_bot_created
  ON messages(bot, conversation_id, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  message_id UNINDEXED,
  bot UNINDEXED,
  role UNINDEXED,
  created_at UNINDEXED,
  body,
  tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS messages_fts_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO messages_fts_meta(key, value) VALUES ('backfill', 'pending');

CREATE TABLE IF NOT EXISTS terminal_logs (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  command TEXT NOT NULL,
  exit_code INTEGER,
  output TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  FOREIGN KEY (bot) REFERENCES bots(name) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_terminal_bot_created
  ON terminal_logs(bot, created_at);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  log_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_bot ON jobs(bot, created_at);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vault_entries (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  kind TEXT NOT NULL,
  origin TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  secret_blob BLOB NOT NULL,
  fields_json TEXT NOT NULL DEFAULT '[]',
  public_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- `bot` stores the stable bot UUID (bots.id), not the slug.
CREATE TABLE IF NOT EXISTS vault_grants (
  bot TEXT NOT NULL,
  entry_id TEXT NOT NULL,
  granted_at TEXT NOT NULL,
  PRIMARY KEY (bot, entry_id),
  FOREIGN KEY (entry_id) REFERENCES vault_entries(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vault_requests (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  kind TEXT NOT NULL,
  entry_id TEXT,
  label TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending',
  message_id TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  fields_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_vault_requests_bot_state
  ON vault_requests(bot, state);

CREATE TABLE IF NOT EXISTS bot_inbox (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  from_bot TEXT,
  kind TEXT NOT NULL,
  content TEXT NOT NULL,
  correlation_id TEXT,
  state TEXT NOT NULL DEFAULT 'queued',
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_bot_inbox_bot_state
  ON bot_inbox(bot, state, created_at);

CREATE TABLE IF NOT EXISTS bot_asks (
  id TEXT PRIMARY KEY,
  from_bot TEXT NOT NULL,
  to_bot TEXT NOT NULL,
  question TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'open',
  answer TEXT,
  inbox_id TEXT,
  created_at TEXT NOT NULL,
  answered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_bot_asks_to_state
  ON bot_asks(to_bot, state);

CREATE INDEX IF NOT EXISTS idx_bot_asks_from_state
  ON bot_asks(from_bot, state);

CREATE TABLE IF NOT EXISTS bot_schedules (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  name TEXT NOT NULL,
  cron TEXT NOT NULL,
  recurring INTEGER NOT NULL DEFAULT 1,
  instruction TEXT NOT NULL DEFAULT '',
  anchor_message_id TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  next_run_at TEXT NOT NULL,
  last_run_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bot_schedules_bot
  ON bot_schedules(bot, enabled);

CREATE INDEX IF NOT EXISTS idx_bot_schedules_due
  ON bot_schedules(enabled, next_run_at);

CREATE TABLE IF NOT EXISTS bot_webhooks (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  name TEXT NOT NULL,
  token TEXT NOT NULL UNIQUE,
  instruction TEXT NOT NULL DEFAULT '',
  anchor_message_id TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bot_webhooks_bot
  ON bot_webhooks(bot, enabled);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bot_webhooks_token
  ON bot_webhooks(token);

CREATE TABLE IF NOT EXISTS memory_entries (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  value TEXT NOT NULL,
  tier TEXT NOT NULL DEFAULT 'browse',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_entries_tier
  ON memory_entries(tier, key);

CREATE TABLE IF NOT EXISTS memory_proposals (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  action TEXT NOT NULL,
  key TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  value TEXT NOT NULL DEFAULT '',
  tier TEXT NOT NULL DEFAULT 'browse',
  reason TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'pending',
  message_id TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_proposals_state
  ON memory_proposals(state, created_at);

CREATE TABLE IF NOT EXISTS approval_requests (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  message_id TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_bot_state
  ON approval_requests(bot, state, created_at);

CREATE TABLE IF NOT EXISTS clarify_requests (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL,
  choices_json TEXT NOT NULL DEFAULT '[]',
  allow_text INTEGER NOT NULL DEFAULT 1,
  state TEXT NOT NULL DEFAULT 'pending',
  message_id TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_clarify_requests_bot_state
  ON clarify_requests(bot, state, created_at);

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  token_hash TEXT,
  created_at TEXT NOT NULL,
  last_seen_at TEXT,
  revoked_at TEXT,
  egress INTEGER NOT NULL DEFAULT 0,
  killswitch INTEGER NOT NULL DEFAULT 0,
  notify INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_token_hash ON devices(token_hash);

CREATE TABLE IF NOT EXISTS device_pairings (
  id TEXT PRIMARY KEY,
  user_code TEXT NOT NULL,
  poll_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  status TEXT NOT NULL,
  device_id TEXT,
  token_once TEXT,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS device_mcp_tools (
  id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  server_name TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  input_schema TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_device_mcp_device ON device_mcp_tools(device_id);

CREATE TABLE IF NOT EXISTS bot_mcp_grants (
  id TEXT PRIMARY KEY,
  bot TEXT NOT NULL REFERENCES bots(name) ON DELETE CASCADE,
  device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  server_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (bot, device_id, server_name)
);

CREATE INDEX IF NOT EXISTS idx_bot_mcp_grants_bot ON bot_mcp_grants(bot);
