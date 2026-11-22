-- Per-bot Pi thinking level (off / minimal / low / medium / high / xhigh / max).
ALTER TABLE bots ADD COLUMN thinking TEXT NOT NULL DEFAULT 'medium';
