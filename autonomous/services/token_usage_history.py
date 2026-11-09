"""Persistent daily token usage history (per bot).

Survives chat clear. Rows are removed when the bot is deleted (FK CASCADE).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autonomous.db import get_db, row_to_dict
from autonomous.services import bots as bots_svc


def _utc_day(when: datetime | None = None) -> str:
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def record_usage(
    bot: str,
    tokens_in: int,
    tokens_out: int,
    *,
    home: Path | None = None,
    day: str | None = None,
) -> None:
    """Add tokens to today's (UTC) bucket for ``bot``."""
    tin = max(0, int(tokens_in or 0))
    tout = max(0, int(tokens_out or 0))
    if tin == 0 and tout == 0:
        return
    day_key = day or _utc_day()
    with get_db(home) as conn:
        conn.execute(
            """
            INSERT INTO bot_token_usage_daily(bot, day, tokens_in, tokens_out)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(bot, day) DO UPDATE SET
              tokens_in = tokens_in + excluded.tokens_in,
              tokens_out = tokens_out + excluded.tokens_out
            """,
            (bot, day_key, tin, tout),
        )


def purge_bot(bot: str, *, home: Path | None = None) -> None:
    """Explicit purge (CASCADE also covers DELETE FROM bots)."""
    with get_db(home) as conn:
        conn.execute("DELETE FROM bot_token_usage_daily WHERE bot = ?", (bot,))


WINDOW_DAYS = 30


def history(*, home: Path | None = None) -> dict[str, Any]:
    """Cumulative daily series for every living bot.

    The ``days`` axis always covers at least the last ``WINDOW_DAYS`` (UTC),
    padded with zeros before the first recorded use. Older history is kept so
    the Settings chart can scroll past the default 30-day viewport.

    Returns::

        {
          "days": ["2026-10-01", ...],
          "series": [
            {
              "bot": "slug",
              "label": "Display",
              "avatar": "renard",
              "avatar_color": 0,
              "daily": [0, 120, ...],
              "cumulative": [0, 120, ...],
            },
            ...
          ],
          "max_cumulative": 120,
        }
    """
    bots = bots_svc.list_bots(home=home)
    today = datetime.now(timezone.utc).date()
    window_start = today - timedelta(days=WINDOW_DAYS - 1)
    if not bots:
        days = []
        cur = window_start
        while cur <= today:
            days.append(cur.isoformat())
            cur += timedelta(days=1)
        return {"days": days, "series": [], "max_cumulative": 0}

    names = [b["name"] for b in bots]
    placeholders = ",".join("?" for _ in names)
    with get_db(home) as conn:
        rows = conn.execute(
            f"""
            SELECT bot, day, tokens_in, tokens_out
            FROM bot_token_usage_daily
            WHERE bot IN ({placeholders})
            ORDER BY day ASC
            """,
            names,
        ).fetchall()

    by_bot: dict[str, dict[str, int]] = {n: {} for n in names}
    first: date | None = None
    for row in rows:
        d = row_to_dict(row)
        bot = d["bot"]
        day_s = d["day"]
        total = int(d["tokens_in"] or 0) + int(d["tokens_out"] or 0)
        by_bot.setdefault(bot, {})[day_s] = total
        try:
            day_d = date.fromisoformat(day_s)
        except ValueError:
            continue
        if first is None or day_d < first:
            first = day_d

    # At least 30 days ending today; keep older history when present.
    start = window_start if first is None else min(first, window_start)

    days: list[str] = []
    cur = start
    while cur <= today:
        days.append(cur.isoformat())
        cur += timedelta(days=1)

    series: list[dict[str, Any]] = []
    max_cum = 0
    for b in bots:
        name = b["name"]
        daily = [int(by_bot.get(name, {}).get(d, 0)) for d in days]
        cumulative: list[int] = []
        running = 0
        for v in daily:
            running += v
            cumulative.append(running)
        if cumulative:
            max_cum = max(max_cum, cumulative[-1], max(cumulative))
        series.append(
            {
                "bot": name,
                "label": b.get("label") or name,
                "avatar": b.get("avatar") or "",
                "avatar_color": int(b.get("avatar_color") or 0),
                "daily": daily,
                "cumulative": cumulative,
            }
        )

    return {"days": days, "series": series, "max_cumulative": max_cum}
