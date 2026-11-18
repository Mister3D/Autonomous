"""Per-model LLM concurrency gates (provider/id).

Two independent caps on the same pool key:

1. **Parallel** (``autonomous.parallelGate``) — every provider call, any size.
2. **Heavy** (``autonomous.heavyGate``) — only calls with estimated tokens ≥
   threshold.

A request waits until both applicable caps have a free slot, then holds one
lease (flagged heavy when it counts toward the heavy pool).

Edited on the model card in Settings → LLM. Absent / disabled → no gate for
that cap. Pi acquires via ``llm_heavy_gate.ts`` before the provider HTTP call.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from autonomous.services.errors import AutonomousError, ValidationError

log = logging.getLogger("autonomous.llm_heavy_gate")

_LEASE_TTL_SEC = 15 * 60
_DEFAULT_WAIT_SEC = 10 * 60

_DEFAULT_MAX_CONCURRENT = 2
_DEFAULT_TOKEN_THRESHOLD = 10000

_lock = threading.Lock()
_cond = threading.Condition(_lock)
# lease_id → {pool, bot, tokens, heavy, acquired_at}
_leases: dict[str, dict[str, Any]] = {}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_heavy(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    enabled = bool(raw.get("enabled"))
    max_concurrent = max(
        1,
        min(
            64,
            _as_int(
                raw.get("maxConcurrent", raw.get("max_concurrent")),
                _DEFAULT_MAX_CONCURRENT,
            ),
        ),
    )
    threshold = max(
        0,
        _as_int(
            raw.get("tokenThreshold", raw.get("token_threshold")),
            _DEFAULT_TOKEN_THRESHOLD,
        ),
    )
    return {
        "enabled": enabled,
        "max_concurrent": max_concurrent,
        "token_threshold": threshold,
    }


def _normalize_parallel(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    enabled = bool(raw.get("enabled"))
    max_concurrent = max(
        1,
        min(
            64,
            _as_int(
                raw.get("maxConcurrent", raw.get("max_concurrent")),
                _DEFAULT_MAX_CONCURRENT,
            ),
        ),
    )
    return {"enabled": enabled, "max_concurrent": max_concurrent}


def heavy_from_entry(entry: dict[str, Any] | None) -> dict[str, Any]:
    """Read ``autonomous.heavyGate`` from a models.json model entry."""
    if not isinstance(entry, dict):
        return _normalize_heavy(None)
    auto = entry.get("autonomous")
    if not isinstance(auto, dict):
        return _normalize_heavy(None)
    return _normalize_heavy(auto.get("heavyGate") or auto.get("heavy_gate"))


def parallel_from_entry(entry: dict[str, Any] | None) -> dict[str, Any]:
    """Read ``autonomous.parallelGate`` (all sizes) from a model entry."""
    if not isinstance(entry, dict):
        return _normalize_parallel(None)
    auto = entry.get("autonomous")
    if not isinstance(auto, dict):
        return _normalize_parallel(None)
    return _normalize_parallel(auto.get("parallelGate") or auto.get("parallel_gate"))


def concurrency_from_entry(entry: dict[str, Any] | None) -> dict[str, Any]:
    """Combined UI/runtime view for both gates."""
    heavy = heavy_from_entry(entry)
    parallel = parallel_from_entry(entry)
    return {
        "parallel_gate_enabled": parallel["enabled"],
        "max_parallel": parallel["max_concurrent"],
        "heavy_gate_enabled": heavy["enabled"],
        "heavy_max_concurrent": heavy["max_concurrent"],
        "heavy_token_threshold": heavy["token_threshold"],
        # Back-compat aliases used by older helpers / tests.
        "enabled": heavy["enabled"],
        "max_concurrent": heavy["max_concurrent"],
        "token_threshold": heavy["token_threshold"],
    }


def pool_key(provider: str, model_id: str) -> str:
    p = (provider or "").strip()
    m = (model_id or "").strip()
    if p and m:
        return f"{p}/{m}"
    return m or p or ""


def resolve_model_ref(
    bot: str,
    model_hint: str | None = None,
    *,
    home: Path | None = None,
) -> tuple[str, str]:
    """Pick provider + model id from the bot row and optional payload model."""
    from autonomous.services import bots as bots_svc
    from autonomous.services.setup_config import split_model_ref

    hint = (model_hint or "").strip()
    if hint and "/" in hint:
        return split_model_ref(hint)

    bot_ref = ""
    try:
        bot_ref = str(bots_svc.get_bot(bot, home=home).get("model") or "").strip()
    except Exception:
        bot_ref = ""
    provider, mid = split_model_ref(bot_ref)
    if hint:
        return provider, hint
    return provider, mid


def gate_config_for_model(
    provider: str,
    model_id: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Concurrency settings for one provider/id (both gates disabled when unset)."""
    del home
    from autonomous.services.setup_config import _read_models_json, find_model_entry

    if not (provider or model_id):
        cfg = concurrency_from_entry(None)
    else:
        data = _read_models_json()
        entry = find_model_entry(data, provider, model_id)
        cfg = concurrency_from_entry(entry)
    cfg["pool"] = pool_key(provider, model_id)
    cfg["provider"] = provider
    cfg["model_id"] = model_id
    return cfg


def estimate_tokens(payload: Any) -> int:
    """Rough prompt-size estimate (chars/4). Good enough to separate 2k from 100k."""

    def walk(node: Any) -> int:
        if node is None:
            return 0
        if isinstance(node, str):
            return len(node)
        if isinstance(node, (int, float, bool)):
            return 8
        if isinstance(node, list):
            return sum(walk(x) for x in node)
        if isinstance(node, dict):
            if node.get("type") in ("image_url", "image", "input_image"):
                return 1200
            total = 0
            for key, value in node.items():
                if key in ("image_url", "image", "source") and isinstance(value, dict):
                    url = value.get("url") or value.get("data") or ""
                    if isinstance(url, str) and url.startswith("data:"):
                        total += 1200
                        continue
                total += walk(value)
            return total
        return 0

    chars = walk(payload)
    return max(0, (chars + 3) // 4)


def _purge_expired_locked(now: float | None = None) -> int:
    now = time.monotonic() if now is None else now
    dead = [
        lid
        for lid, meta in _leases.items()
        if now - float(meta.get("acquired_at") or 0) > _LEASE_TTL_SEC
    ]
    for lid in dead:
        log.warning("llm heavy gate: expired lease %s (%s)", lid, _leases.get(lid))
        _leases.pop(lid, None)
    return len(dead)


def _active_for_pool_locked(pool: str, *, heavy_only: bool = False) -> int:
    n = 0
    for meta in _leases.values():
        if meta.get("pool") != pool:
            continue
        if heavy_only and not meta.get("heavy"):
            continue
        n += 1
    return n


def snapshot(home: Path | None = None) -> dict[str, Any]:
    """Debug / tests: current leases."""
    del home
    with _cond:
        _purge_expired_locked()
        leases = [
            {
                "lease_id": lid,
                "pool": meta.get("pool"),
                "bot": meta.get("bot"),
                "tokens": meta.get("tokens"),
                "heavy": bool(meta.get("heavy")),
                "age_sec": round(time.monotonic() - float(meta.get("acquired_at") or 0), 1),
            }
            for lid, meta in _leases.items()
        ]
    by_pool: dict[str, int] = {}
    for row in leases:
        p = str(row.get("pool") or "")
        by_pool[p] = by_pool.get(p, 0) + 1
    return {"active": len(leases), "by_pool": by_pool, "leases": leases}


def reset_for_tests() -> None:
    """Drop every lease (pytest only)."""
    with _cond:
        _leases.clear()
        _cond.notify_all()


def acquire(
    bot: str,
    tokens: int,
    *,
    model: str | None = None,
    home: Path | None = None,
    wait_sec: float | None = None,
) -> dict[str, Any]:
    """Block until applicable slots are free, or skip when no gate applies."""
    bot = (bot or "").strip()
    if not bot:
        raise ValidationError("bot required", code="llm_heavy_gate_bot")
    try:
        tokens = max(0, int(tokens))
    except (TypeError, ValueError) as exc:
        raise ValidationError("tokens must be an integer", code="llm_heavy_gate_tokens") from exc

    provider, model_id = resolve_model_ref(bot, model, home=home)
    cfg = gate_config_for_model(provider, model_id, home=home)
    pool = cfg.get("pool") or pool_key(provider, model_id)

    parallel_on = bool(cfg.get("parallel_gate_enabled"))
    heavy_on = bool(cfg.get("heavy_gate_enabled") or cfg.get("enabled"))
    threshold = int(cfg.get("heavy_token_threshold") or cfg.get("token_threshold") or 0)
    max_parallel = max(
        1,
        int(cfg.get("max_parallel") or _DEFAULT_MAX_CONCURRENT),
    )
    max_heavy = max(
        1,
        int(
            cfg.get("heavy_max_concurrent")
            if cfg.get("heavy_max_concurrent") is not None
            else (cfg.get("max_concurrent") or _DEFAULT_MAX_CONCURRENT)
        ),
    )

    counts_heavy = heavy_on and tokens >= threshold
    needs_lease = bool(pool) and (parallel_on or counts_heavy)

    if not needs_lease:
        return {
            "heavy": False,
            "lease_id": None,
            "tokens": tokens,
            "pool": pool or None,
            "threshold": threshold,
            "max_concurrent": max_heavy,
            "max_parallel": max_parallel,
            "active": _active_count(pool) if pool else 0,
        }

    limit = float(_DEFAULT_WAIT_SEC if wait_sec is None else wait_sec)
    limit = max(1.0, min(limit, 30 * 60))
    deadline = time.monotonic() + limit

    with _cond:
        while True:
            _purge_expired_locked()
            active_all = _active_for_pool_locked(pool)
            active_heavy = _active_for_pool_locked(pool, heavy_only=True)
            blocked_parallel = parallel_on and active_all >= max_parallel
            blocked_heavy = counts_heavy and active_heavy >= max_heavy
            if not blocked_parallel and not blocked_heavy:
                lease_id = uuid.uuid4().hex
                _leases[lease_id] = {
                    "pool": pool,
                    "bot": bot,
                    "tokens": tokens,
                    "heavy": counts_heavy,
                    "acquired_at": time.monotonic(),
                }
                log.info(
                    "llm gate: acquired %s pool=%s bot=%s tokens=%s heavy=%s "
                    "all=%s/%s heavy_slots=%s/%s",
                    lease_id,
                    pool,
                    bot,
                    tokens,
                    counts_heavy,
                    active_all + 1,
                    max_parallel if parallel_on else "∞",
                    active_heavy + (1 if counts_heavy else 0),
                    max_heavy if heavy_on else "∞",
                )
                return {
                    "heavy": counts_heavy,
                    "lease_id": lease_id,
                    "tokens": tokens,
                    "pool": pool,
                    "threshold": threshold,
                    "max_concurrent": max_heavy,
                    "max_parallel": max_parallel,
                    "active": active_all + 1,
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if blocked_parallel:
                    raise AutonomousError(
                        "Timed out waiting for a parallel LLM slot on "
                        f"{pool} ({max_parallel} concurrent, any size).",
                        code="llm_heavy_gate_timeout",
                    )
                raise AutonomousError(
                    "Timed out waiting for a large-LLM slot on "
                    f"{pool} ({max_heavy} concurrent ≥ {threshold} tokens).",
                    code="llm_heavy_gate_timeout",
                )
            _cond.wait(timeout=min(1.0, remaining))


def release(lease_id: str | None) -> dict[str, Any]:
    """Free a lease (idempotent)."""
    lid = (lease_id or "").strip()
    if not lid:
        return {"ok": True, "released": False, "active": len(_leases)}
    with _cond:
        meta = _leases.pop(lid, None)
        if meta is not None:
            pool = str(meta.get("pool") or "")
            _cond.notify_all()
            active = _active_for_pool_locked(pool) if pool else len(_leases)
            log.info(
                "llm gate: released %s pool=%s bot=%s active=%s",
                lid,
                pool,
                meta.get("bot"),
                active,
            )
            return {"ok": True, "released": True, "pool": pool or None, "active": active}
        return {"ok": True, "released": False, "active": len(_leases)}


def _active_count(pool: str | None = None) -> int:
    with _cond:
        _purge_expired_locked()
        if pool:
            return _active_for_pool_locked(pool)
        return len(_leases)
