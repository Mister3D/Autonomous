"""Minimal 5-field cron matcher/next-fire calculator (UTC instants, no external deps).

Fields: minute hour day-of-month month day-of-week
- day-of-week: 0-6 or 7 = Sunday (cron style)
- Supports: N, *, */n, a-b, a-b/n, comma lists

Stored expressions are UTC. Callers convert host-local input via
`local_cron_to_utc` / `utc_cron_to_local` (fixed offset at conversion time).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_FIELD_RE = re.compile(
    r"^(?:(?:\*(?:/\d+)?)|(?:\d+(?:-\d+)?(?:/\d+)?)(?:,(?:\d+(?:-\d+)?(?:/\d+)?))*)$"
)


def _parse_field(expr: str, minimum: int, maximum: int) -> set[int]:
    expr = (expr or "").strip()
    if not expr or not _FIELD_RE.match(expr):
        raise ValueError(f"Invalid cron field: {expr!r}")
    out: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError(f"Invalid cron step: {part!r}")
        else:
            base = part
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(base)
        if start > end or start < minimum or end > maximum:
            raise ValueError(f"Cron field out of range: {part!r}")
        for v in range(start, end + 1, step):
            out.add(v)
    return out


def parse_cron(expr: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    parts = (expr or "").strip().split()
    if len(parts) != 5:
        raise ValueError("Cron must have 5 fields: minute hour dom month dow (UTC)")
    minute = _parse_field(parts[0], 0, 59)
    hour = _parse_field(parts[1], 0, 23)
    dom = _parse_field(parts[2], 1, 31)
    month = _parse_field(parts[3], 1, 12)
    raw_dow = _parse_field(parts[4], 0, 7)
    # Normalize 7 → 0 (Sunday)
    dow = {(d % 7) for d in raw_dow}
    return minute, hour, dom, month, dow


def validate_cron(expr: str) -> str:
    parse_cron(expr)
    return " ".join((expr or "").strip().split())


def _matches(dt: datetime, fields: tuple[set[int], ...]) -> bool:
    minute, hour, dom, month, dow = fields
    # Cron DOM/DOW: if either is unrestricted (* covers all), AND both constrained
    # → match if either matches (standard cron). Our parser expands *; treat
    # "all values" as unrestricted.
    dom_star = len(dom) == 31
    dow_star = len(dow) == 7
    if dt.minute not in minute or dt.hour not in hour or dt.month not in month:
        return False
    if dom_star and dow_star:
        return True
    if not dom_star and not dow_star:
        return dt.day in dom or dt.weekday() in _dow_py(dow)
    if not dom_star:
        return dt.day in dom
    return dt.weekday() in _dow_py(dow)


def _dow_py(dow: set[int]) -> set[int]:
    """Cron DOW 0=Sun..6=Sat → Python weekday() Mon=0..Sun=6."""
    out: set[int] = set()
    for d in dow:
        out.add(6 if d == 0 else d - 1)
    return out


def next_run_after(cron: str, after: datetime) -> datetime:
    """Next UTC minute >= after+1min that matches cron."""
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    else:
        after = after.astimezone(timezone.utc)
    fields = parse_cron(cron)
    # Start at next whole minute
    cursor = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    # Bound search (~2 years of minutes is too much; step smartly)
    limit = cursor + timedelta(days=400)
    while cursor <= limit:
        # Fast-forward month
        if cursor.month not in fields[3]:
            # jump to 1st of next matching month
            y, m = cursor.year, cursor.month
            found = False
            for _ in range(24):
                m += 1
                if m > 12:
                    m = 1
                    y += 1
                if m in fields[3]:
                    cursor = datetime(y, m, 1, 0, 0, tzinfo=timezone.utc)
                    found = True
                    break
            if not found:
                break
            continue
        if _matches(cursor, fields):
            return cursor
        cursor += timedelta(minutes=1)
    raise ValueError(f"No next run found for cron {cron!r}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_utc(s: str) -> datetime:
    text = (s or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def host_offset_minutes(at: datetime | None = None) -> int:
    """Host local offset east of UTC, in minutes (e.g. 120 for UTC+2)."""
    if at is None:
        moment = datetime.now().astimezone()
    elif at.tzinfo is None:
        moment = at.replace(tzinfo=timezone.utc).astimezone()
    else:
        moment = at.astimezone()
    off = moment.utcoffset() or timedelta(0)
    return int(off.total_seconds() // 60)


def format_utc_offset(minutes: int | None = None) -> str:
    if minutes is None:
        minutes = host_offset_minutes()
    sign = "+" if minutes >= 0 else "-"
    total = abs(int(minutes))
    hours, mins = divmod(total, 60)
    return f"{sign}{hours:02d}:{mins:02d}"


def host_tz_name() -> str:
    """IANA name when the OS exposes one, else a short label."""
    env = (os.environ.get("TZ") or "").strip()
    if env:
        if env.upper() in {"UTC", "ETC/UTC", "GMT", "ETC/GMT"}:
            return "UTC"
        return env
    try:
        parts = Path("/etc/localtime").resolve().parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1 :])
            if name.upper() in {"UTC", "ETC/UTC", "ETC/GMT", "GMT"}:
                return "UTC"
            if name:
                return name
    except OSError:
        pass
    if host_offset_minutes() == 0:
        return "UTC"
    now = datetime.now().astimezone()
    return now.tzname() or "local"


def host_clock() -> dict[str, str]:
    return {
        "timezone": host_tz_name(),
        "utc_offset": format_utc_offset(),
    }


def _emit_field(values: set[int], minimum: int, maximum: int) -> str:
    vals = sorted(values)
    if not vals:
        raise ValueError("empty cron field")
    if vals == list(range(minimum, maximum + 1)):
        return "*"
    if len(vals) == 1:
        return str(vals[0])
    step = vals[1] - vals[0]
    if step > 0 and vals == list(range(vals[0], vals[-1] + 1, step)):
        if vals[0] == minimum and vals == list(range(minimum, maximum + 1, step)):
            return f"*/{step}" if step != 1 else "*"
        if step == 1:
            return f"{vals[0]}-{vals[-1]}"
        if len(vals) == 2:
            return ",".join(str(v) for v in vals)
        return f"{vals[0]}-{vals[-1]}/{step}"
    return ",".join(str(v) for v in vals)


def shift_cron(expr: str, delta_minutes: int) -> str:
    """Shift every minute/hour slot by `delta_minutes`.

    Day-of-month and day-of-week move only when every slot crosses the same
    number of midnights. Mixed crossings (or a day-of-month that leaves 1–31)
    raise ValueError — the 5-field form cannot represent them.
    """
    minute, hour, dom, month, dow = parse_cron(expr)
    new_minutes: set[int] = set()
    new_hours: set[int] = set()
    day_shifts: set[int] = set()
    span = 24 * 60
    for h in hour:
        for m in minute:
            total = h * 60 + m + int(delta_minutes)
            day_shifts.add(total // span)
            mod = total % span
            nh, nm = divmod(mod, 60)
            new_hours.add(nh)
            new_minutes.add(nm)
    dom_star = len(dom) == 31
    dow_star = len(dow) == 7
    if len(day_shifts) > 1 and not (dom_star and dow_star):
        raise ValueError(
            "Cron cannot be converted across this UTC offset: slots cross "
            "midnight differently. Use one hour, or * for both day fields."
        )
    day_delta = 0 if len(day_shifts) != 1 else next(iter(day_shifts))
    if day_delta and not dom_star:
        shifted: set[int] = set()
        for day in dom:
            nxt = day + day_delta
            if nxt < 1 or nxt > 31:
                raise ValueError(
                    "Cron day-of-month leaves 1–31 when converted across the UTC offset."
                )
            shifted.add(nxt)
        dom = shifted
    if day_delta and not dow_star:
        dow = {(d + day_delta) % 7 for d in dow}
    return " ".join(
        [
            _emit_field(new_minutes, 0, 59),
            _emit_field(new_hours, 0, 23),
            _emit_field(dom, 1, 31),
            _emit_field(month, 1, 12),
            _emit_field(dow, 0, 6),
        ]
    )


def valid_tz_name(name: str) -> bool:
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(name)
    except Exception:
        return False
    return True


def zone_offset_minutes(tz_name: str, at: datetime | None = None) -> int:
    """Offset east of UTC for an IANA zone, in minutes."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz_name)
    if at is None:
        moment = datetime.now(timezone.utc).astimezone(zone)
    elif at.tzinfo is None:
        moment = at.replace(tzinfo=timezone.utc).astimezone(zone)
    else:
        moment = at.astimezone(zone)
    off = moment.utcoffset() or timedelta(0)
    return int(off.total_seconds() // 60)


def _offset_minutes(tz_name: str | None, at: datetime | None) -> int:
    if tz_name:
        return zone_offset_minutes(tz_name, at)
    return host_offset_minutes(at)


def user_tz_name(home=None) -> str | None:
    """IANA zone from settings, or None to keep the host clock."""
    from autonomous.services import settings as settings_svc

    raw = settings_svc.get("timezone", home=home, default="") or ""
    name = str(raw).strip()
    if name and valid_tz_name(name):
        return name
    return None


def format_local(moment: datetime, tz_name: str | None) -> str:
    """Wall clock `YYYY-MM-DD HH:MM` in `tz_name`, or on the host if unset."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    if tz_name:
        from zoneinfo import ZoneInfo

        local = moment.astimezone(ZoneInfo(tz_name))
    else:
        local = moment.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def user_clock(home=None) -> dict[str, str]:
    """Timezone used to display and accept schedule crons, plus the local now."""
    name = user_tz_name(home)
    now = datetime.now(timezone.utc)
    if not name:
        clock = host_clock()
        clock["now"] = format_local(now, None)
        return clock
    return {
        "timezone": name,
        "utc_offset": format_utc_offset(zone_offset_minutes(name, now)),
        "now": format_local(now, name),
    }


def normalize_tz_setting(value) -> str:
    """Empty clears the setting (host clock). Anything else must be IANA."""
    from autonomous.services.errors import ValidationError

    name = str(value or "").strip()
    if not name:
        return ""
    if not valid_tz_name(name):
        raise ValidationError(f"fuseau inconnu : {name}", code="invalid_timezone")
    return name


def local_cron_to_utc(
    expr: str, *, at: datetime | None = None, tz_name: str | None = None
) -> str:
    """Local 5-field cron → UTC. `tz_name` is the user zone; else the host offset."""
    return shift_cron(expr, -_offset_minutes(tz_name, at))


def utc_cron_to_local(
    expr: str, *, at: datetime | None = None, tz_name: str | None = None
) -> str:
    """UTC 5-field cron → local. `tz_name` is the user zone; else the host offset."""
    return shift_cron(expr, _offset_minutes(tz_name, at))
