"""Chat message search — SQLite FTS5 (lexical) + phrase search via LLM."""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path
from typing import Any

from autonomous.db import get_db
from autonomous.services import bots as bots_svc
from autonomous.services.errors import ValidationError

log = logging.getLogger("autonomous.search")

_INDEX_ROLES = frozenset({"user", "assistant", "system"})
_MAX_LIMIT = 50
_DEFAULT_LIMIT = 20
_NL_MIN_LEN = 40

_STOPWORDS = frozenset(
    """
    a à au aux avec ce ces cet cette dans de des du elle en et eux il ils je la le les leur
    lui ma me mes moi mon ne nos notre nous on ou par pas pour qu que qui sa se ses sois
    son sur ta te tes toi ton tu un une vos votre vous y d l n s c j t m qu'
    the a an and or of to in for on at is are was were be been being it this that these those
    my your his her their our we you they i me him them with from by as at into about
    le la les un une des de du au aux et ou mais donc car ni
    mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs
    qui que quoi dont où quand comment pourquoi lequel laquelle lesquels lesquelles
    est suis es sommes êtes sont était étaient ai as a avons avez ont
    message messages chat conversation bot bots parle parlé parlais parlait parler
    trouve retrouver cherche chercher recherche
    """.split()
)

_NL_HINT_RE = re.compile(
    r"(?i)\b("
    r"qui|quoi|quand|où|ou|comment|pourquoi|quel|quelle|quels|quelles|"
    r"parl[ée]e?s?|message|conversation|retrouve|cherche|où\s+on|est[- ]ce\s+que|"
    r"where|when|what|which|who|how|find|message|talked|about"
    r")\b"
)


def _meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
    return {}


def _should_index(role: str, content: str, meta: dict[str, Any]) -> bool:
    if role not in _INDEX_ROLES:
        return False
    if meta.get("hidden_prompt") or meta.get("queued"):
        return False
    if meta.get("streaming") and not (content or "").strip():
        return False
    if not (content or "").strip():
        return False
    # Tool / card dumps that slipped into system are rare; skip obvious tool markers.
    kind = str(meta.get("kind") or "")
    if kind in {
        "tool",
        "vault_request",
        "memory_proposal",
        "approval_request",
        "clarify_request",
        "desk_request",
    }:
        return False
    return True


def ensure_fts(home: Path | None = None) -> None:
    """Create FTS table if missing and backfill once."""
    with get_db(home) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        ).fetchone()
        if not row:
            return
        meta = conn.execute(
            "SELECT value FROM messages_fts_meta WHERE key='backfill'"
        ).fetchone()
        if meta and meta["value"] == "done":
            return
        conn.execute("DELETE FROM messages_fts")
        rows = conn.execute(
            "SELECT id, bot, role, content, meta_json, created_at FROM messages"
        ).fetchall()
        n = 0
        for r in rows:
            meta_d = _meta(r["meta_json"])
            if not _should_index(r["role"], r["content"] or "", meta_d):
                continue
            conn.execute(
                """
                INSERT INTO messages_fts(message_id, bot, role, created_at, body)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    r["id"],
                    r["bot"],
                    r["role"],
                    r["created_at"],
                    r["content"] or "",
                ),
            )
            n += 1
        conn.execute(
            "INSERT INTO messages_fts_meta(key, value) VALUES ('backfill', 'done') "
            "ON CONFLICT(key) DO UPDATE SET value='done'"
        )
        log.info("messages_fts backfill: %s rows", n)


def index_message(message: dict[str, Any], *, home: Path | None = None) -> None:
    """Upsert one message into FTS (no-op if not indexable)."""
    msg_id = message.get("id")
    if not msg_id:
        return
    role = str(message.get("role") or "")
    content = str(message.get("content") or "")
    meta = _meta(message.get("meta"))
    try:
        with get_db(home) as conn:
            conn.execute(
                "DELETE FROM messages_fts WHERE message_id = ?", (msg_id,)
            )
            if not _should_index(role, content, meta):
                return
            conn.execute(
                """
                INSERT INTO messages_fts(message_id, bot, role, created_at, body)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    message.get("bot") or "",
                    role,
                    message.get("created_at") or "",
                    content,
                ),
            )
    except Exception:
        log.exception("FTS index failed for %s", msg_id)


def remove_message(message_id: str, *, home: Path | None = None) -> None:
    if not message_id:
        return
    try:
        with get_db(home) as conn:
            conn.execute(
                "DELETE FROM messages_fts WHERE message_id = ?", (message_id,)
            )
    except Exception:
        log.exception("FTS remove failed for %s", message_id)


def clear_bot_index(bot: str, *, home: Path | None = None) -> None:
    try:
        with get_db(home) as conn:
            conn.execute("DELETE FROM messages_fts WHERE bot = ?", (bot,))
    except Exception:
        log.exception("FTS clear failed for bot %s", bot)


def _tokenize(query: str) -> list[str]:
    raw = re.findall(r"[0-9A-Za-zÀ-ÿ_]{2,}", query or "", flags=re.UNICODE)
    out: list[str] = []
    seen: set[str] = set()
    for tok in raw:
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(tok)
    return out


def _fts_query(tokens: list[str], *, op: str = "AND") -> str:
    if not tokens:
        return ""
    parts = []
    for t in tokens:
        safe = t.replace('"', " ").strip()
        if not safe:
            continue
        parts.append(f'"{safe}"')
    if not parts:
        return ""
    joiner = " AND " if op.upper() == "AND" else " OR "
    return joiner.join(parts)


def looks_like_nl(query: str) -> bool:
    q = (query or "").strip()
    if len(q) >= _NL_MIN_LEN:
        return True
    # Short questions / phrases (« où j'habite », « mon adresse ») → semantic.
    if len(q) >= 8 and _NL_HINT_RE.search(q) and (
        " " in q or "'" in q or "’" in q or "?" in q
    ):
        return True
    # Multi-word phrases (« Site d'achat », « dernière commande ») → semantic,
    # not strict AND over the typed words.
    if len(_tokenize(q)) >= 2:
        return True
    return False


def _snippet(body: str, query: str, *, radius: int = 72) -> str:
    text = re.sub(r"\s+", " ", (body or "").strip())
    if not text:
        return ""
    low = text.lower()
    hit_at = -1
    for tok in _tokenize(query):
        i = low.find(tok.lower())
        if i >= 0:
            hit_at = i
            break
    if hit_at < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, hit_at - radius)
    end = min(len(text), hit_at + radius)
    snip = text[start:end]
    if start > 0:
        snip = "…" + snip
    if end < len(text):
        snip = snip + "…"
    return snip


def _bot_label(bot: str, *, home: Path | None = None) -> str:
    try:
        row = bots_svc.get_bot(bot, home=home)
        return str(row.get("label") or row.get("name") or bot)
    except Exception:
        return bot


def search_lexical(
    query: str,
    *,
    bot: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        raise ValidationError("q required", code="search_empty")
    limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    ensure_fts(home)
    tokens = _tokenize(q)
    # Phrase-ish: also try the whole query as one token group.
    fts = _fts_query(tokens, op="AND") if tokens else ""
    if not fts:
        # Fallback: quote whole query for FTS prefix-ish match.
        safe = q.replace('"', " ").strip()
        fts = f'"{safe}"' if safe else ""
    if not fts:
        return []

    sql = """
        SELECT message_id, bot, role, created_at, body,
               bm25(messages_fts) AS rank
        FROM messages_fts
        WHERE messages_fts MATCH ?
    """
    params: list[Any] = [fts]
    if bot:
        sql += " AND bot = ?"
        params.append(bot)
    sql += " ORDER BY rank, created_at DESC LIMIT ?"
    params.append(limit)

    with get_db(home) as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            # Bad MATCH syntax → empty rather than 500.
            log.exception("FTS MATCH failed for %r", fts)
            return []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "message_id": r["message_id"],
                "bot": r["bot"],
                "bot_label": _bot_label(r["bot"], home=home),
                "role": r["role"],
                "created_at": r["created_at"],
                "snippet": _snippet(r["body"] or "", q),
                "score": float(r["rank"] or 0),
                "mode": "lexical",
            }
        )
    return out


def _hit_from_row(
    r: Any, *, query: str, home: Path | None, mode: str, score: float = 0.0
) -> dict[str, Any]:
    return {
        "message_id": r["message_id"],
        "bot": r["bot"],
        "bot_label": _bot_label(r["bot"], home=home),
        "role": r["role"],
        "created_at": r["created_at"],
        "snippet": _snippet(r["body"] or "", query),
        "score": score,
        "mode": mode,
    }


def _fts_or_terms(
    terms: list[str],
    *,
    bot: str | None = None,
    limit: int = 40,
    query_for_snippet: str = "",
    home: Path | None = None,
    mode: str = "nl",
) -> list[dict[str, Any]]:
    ensure_fts(home)
    tokens = []
    seen: set[str] = set()
    for t in terms:
        for piece in _tokenize(t) or ([t] if len(t.strip()) >= 2 else []):
            low = piece.lower()
            if low in seen or low in _STOPWORDS:
                continue
            seen.add(low)
            tokens.append(piece)
    fts = _fts_query(tokens, op="OR")
    if not fts:
        return []
    sql = """
        SELECT message_id, bot, role, created_at, body,
               bm25(messages_fts) AS rank
        FROM messages_fts
        WHERE messages_fts MATCH ?
    """
    params: list[Any] = [fts]
    if bot:
        sql += " AND bot = ?"
        params.append(bot)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    with get_db(home) as conn:
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            log.exception("FTS OR failed for %r", fts)
            return []
    return [
        _hit_from_row(
            r,
            query=query_for_snippet,
            home=home,
            mode=mode,
            score=-float(r["rank"] or 0),
        )
        for r in rows
    ]


def _recent_hits(
    *,
    bot: str | None = None,
    limit: int = 80,
    query_for_snippet: str = "",
    home: Path | None = None,
) -> list[dict[str, Any]]:
    ensure_fts(home)
    sql = """
        SELECT message_id, bot, role, created_at, body
        FROM messages_fts
    """
    params: list[Any] = []
    if bot:
        sql += " WHERE bot = ?"
        params.append(bot)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_db(home) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        _hit_from_row(r, query=query_for_snippet, home=home, mode="nl", score=0.0)
        for r in rows
    ]


def _llm_config() -> dict[str, str] | None:
    """Resolve OpenAI-compatible endpoint from ~/.pi/agent/models.json + env."""
    try:
        from autonomous.services.pi_status import list_models, models_json_path, pi_env
    except Exception:
        return None
    env = pi_env()
    models = []
    try:
        models = list_models()
    except Exception:
        models = []
    provider = ""
    model_id = ""
    if models:
        provider = str(models[0].get("provider") or "")
        model_id = str(models[0].get("id") or "")
    base = ""
    key = ""
    path = models_json_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            providers = data.get("providers") if isinstance(data, dict) else None
            if isinstance(providers, dict):
                # Prefer the listed model's provider, else first openai-compatible.
                order = [provider] if provider in providers else []
                order.extend(k for k in providers if k not in order)
                for name in order:
                    conf = providers.get(name) or {}
                    if not isinstance(conf, dict):
                        continue
                    api = str(conf.get("api") or "")
                    if api and "openai" not in api.lower() and api != "openai-completions":
                        continue
                    base = str(conf.get("baseUrl") or conf.get("base_url") or "").rstrip("/")
                    key = str(conf.get("apiKey") or conf.get("api_key") or "")
                    if not model_id:
                        mods = conf.get("models") or []
                        if mods and isinstance(mods[0], dict):
                            model_id = str(mods[0].get("id") or "")
                    if not provider:
                        provider = name
                    if base:
                        break
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    # Env overrides / fills gaps (${VAR} style keys often live only in env).
    if key.startswith("${") and key.endswith("}"):
        key = env.get(key[2:-1], "") or ""
    key = (
        key
        or env.get(f"{provider.upper()}_API_KEY")
        or env.get("AUTONOMOUS_LLM_API_KEY")
        or env.get("MISTER3D_API_KEY")  # legacy name
        or env.get("OPENAI_API_KEY")
        or ""
    )
    base = (
        base
        or env.get(f"{provider.upper()}_BASE_URL")
        or env.get("AUTONOMOUS_LLM_BASE_URL")
        or env.get("MISTER3D_BASE_URL")  # legacy name
        or env.get("OPENAI_BASE_URL")
        or ""
    ).rstrip("/")
    if not base and provider.lower() == "ollama":
        base = env.get("OLLAMA_HOST", "http://127.0.0.1:11434/v1").rstrip("/")
        if not base.endswith("/v1"):
            base = base.rstrip("/") + "/v1"
        key = key or "ollama"
    if not base or not model_id:
        return None
    if not key and provider.lower() != "ollama":
        return None
    return {"base_url": base, "model": model_id, "api_key": key or "x"}


def _llm_complete(
    user_prompt: str,
    *,
    system: str,
    max_tokens: int = 300,
    timeout: float = 45.0,
) -> str | None:
    cfg = _llm_config()
    if not cfg:
        return None
    # Same SSRF gate as Settings / grounding (metadata & link-local blocked).
    from autonomous.services.setup_config import assert_safe_outbound_url, urlopen_safe

    base = str(cfg["base_url"] or "").rstrip("/")
    try:
        assert_safe_outbound_url(base)
    except ValidationError:
        log.warning("search LLM base_url blocked by SSRF gate: %s", base[:120])
        return None
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    url = f"{base}/chat/completions"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen_safe(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return str(payload["choices"][0]["message"]["content"] or "")
    except ValidationError:
        log.warning("search LLM request blocked by SSRF gate")
        return None
    except Exception:
        log.exception("search LLM call failed")
        return None


def _parse_csv_terms(text: str) -> list[str]:
    parts = re.split(r"[,;\n]+", text or "")
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        term = p.strip().strip("-•* ").strip("\"'`")
        if len(term) < 2:
            continue
        low = term.lower()
        if low in seen or low in _STOPWORDS:
            continue
        seen.add(low)
        out.append(term)
    return out


def _llm_expand_query(query: str) -> list[str] | None:
    """Ask the LLM for concrete words likely to appear in matching messages."""
    prompt = (
        "L'utilisateur cherche un ancien message de chat avec cette demande :\n"
        f"« {query} »\n\n"
        "Donne 5 à 12 mots ou courtes expressions (français) qui ont de fortes "
        "chances d'apparaître DANS le message cherché (synonymes, lieux, objets, "
        "noms propres possibles). Pas de phrase complète. "
        "Réponds UNIQUEMENT une liste séparée par des virgules."
    )
    text = _llm_complete(
        prompt,
        system="Tu aides une recherche plein texte. Réponse courte, mots seulement.",
        max_tokens=120,
    )
    if text is None:
        return None
    terms = _parse_csv_terms(text)
    return terms or None


def _llm_pick_relevant(
    query: str,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Ask the LLM which candidates answer the question. Drops irrelevant hits."""
    if not candidates:
        return []
    lines = []
    for c in candidates[:24]:
        label = c.get("bot_label") or c.get("bot") or ""
        lines.append(
            f"- id={c['message_id']} bot={label} ({c.get('bot')}) role={c['role']}: "
            f"{(c.get('snippet') or '')[:220]}"
        )
    prompt = (
        "Demande de l'utilisateur :\n"
        f"« {query} »\n\n"
        "Messages candidats :\n"
        + "\n".join(lines)
        + "\n\n"
        "Quels messages correspondent au SENS de la demande "
        "(synonymes, reformulations, entités liées, nom du bot si pertinent) ? "
        "Inclus un message même si les mots exacts de la requête n'y figurent pas. "
        "Réponds UNIQUEMENT avec les UUID du plus pertinent au moins pertinent, "
        "séparés par des virgules. Si vraiment aucun : NONE."
    )
    text = _llm_complete(
        prompt,
        system=(
            "Tu filtres une recherche sémantique de chat. "
            "Juge le sens, pas la présence exacte des mots. Réponse courte."
        ),
        max_tokens=220,
    )
    if text is None:
        return None
    if re.search(r"(?i)\bNONE\b", text.strip()) and not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-", text, flags=re.I
    ):
        return []
    ids = re.findall(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        text,
        flags=re.I,
    )
    by_id = {c["message_id"]: c for c in candidates}
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for mid in ids:
        if mid in seen or mid not in by_id:
            continue
        seen.add(mid)
        item = dict(by_id[mid])
        item["mode"] = "nl_semantic"
        ranked.append(item)
    return ranked


def search_nl(
    query: str,
    *,
    bot: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    home: Path | None = None,
    use_llm: bool = True,
) -> list[dict[str, Any]]:
    """Phrase search: LLM expands meaning → FTS candidates → LLM keeps only relevant.

    Does not rely on exact words from the user phrase. Requires a configured LLM
    when use_llm=True (default).
    """
    q = (query or "").strip()
    if not q:
        raise ValidationError("q required", code="search_empty")
    limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    ensure_fts(home)

    if not use_llm:
        raise ValidationError(
            "Recherche par phrase indisponible sans LLM",
            code="search_nl_no_llm",
        )
    if _llm_config() is None:
        raise ValidationError(
            "Recherche par phrase indisponible : configure un modèle LLM "
            "(~/.pi/agent/models.json + clé API).",
            code="search_nl_no_llm",
        )

    expanded = _llm_expand_query(q)
    # Also search bot labels/names that look like shops (fnac, amazon…).
    label_terms: list[str] = []
    try:
        for b in bots_svc.list_bots(home=home):
            for piece in (b.get("label"), b.get("name")):
                if piece and len(str(piece).strip()) >= 3:
                    label_terms.append(str(piece).strip())
    except Exception:
        pass

    candidates: list[dict[str, Any]] = []
    seed_terms = list(expanded or []) + label_terms
    if seed_terms:
        candidates = _fts_or_terms(
            seed_terms,
            bot=bot,
            limit=max(40, limit * 3),
            query_for_snippet=q,
            home=home,
            mode="nl_semantic",
        )

    # Enrich with recent messages so meaning can match without shared words.
    recent = _recent_hits(
        bot=bot, limit=80, query_for_snippet=q, home=home
    )
    by_id = {c["message_id"]: c for c in candidates}
    for c in recent:
        by_id.setdefault(c["message_id"], c)
    pool = list(by_id.values())

    picked = _llm_pick_relevant(q, pool)
    if picked is None:
        raise ValidationError(
            "Recherche par phrase échouée (LLM).",
            code="search_nl_llm_failed",
        )
    # If the judge was too strict but expansion already found hits, keep those.
    if not picked and candidates:
        for c in candidates:
            c = dict(c)
            c["mode"] = "nl_semantic"
            picked.append(c)
    return picked[:limit]


def search_messages(
    query: str,
    *,
    bot: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    mode: str = "auto",
    home: Path | None = None,
) -> dict[str, Any]:
    """Unified search. mode=auto|lexical|nl."""
    q = (query or "").strip()
    if not q:
        raise ValidationError("q required", code="search_empty")
    mode_l = (mode or "auto").strip().lower()
    if mode_l not in {"auto", "lexical", "nl"}:
        raise ValidationError("mode must be auto|lexical|nl", code="search_bad_mode")
    if bot:
        bots_svc.get_bot(bot, home=home)

    used = mode_l
    if mode_l == "auto":
        used = "nl" if looks_like_nl(q) else "lexical"

    if used == "nl":
        hits = search_nl(q, bot=bot, limit=limit, home=home)
        used = hits[0]["mode"] if hits else "nl_semantic"
    else:
        hits = search_lexical(q, bot=bot, limit=limit, home=home)

    return {"query": q, "mode": used, "hits": hits, "count": len(hits)}
