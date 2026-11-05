-- Per-bot API tokens for Pi (SHA-256 in bots.api_token_hash).
-- Column is also ensured in migrate() via _ensure_column for DBs whose
-- schema_migrations already used low version numbers (pre-squash 1..22).
-- This file is a no-op marker so upgraded installs record version 23.
SELECT 1;
