"""Web-editable configuration: Pi LLM provider + grounding (UI-TARS; the LLM verifies clicks).

Secrets never leave the server: readers return ``{"set": bool, "hint": "…abcd"}``.
Writers keep unrelated entries, write atomically and chmod 600.

Precedence is unchanged: a process environment variable wins over files, so a
value coming from the environment is reported as ``source: "env"`` and is
read-only in the UI.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from autonomous.paths import ensure_home
from autonomous.services.errors import ValidationError

PI_API = "openai-completions"
DEFAULT_PROVIDER = "autonomous"
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
# Hostnames / nets blocked for admin SSRF (cloud metadata, link-local).
_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
}


# ── helpers ────────────────────────────────────────────────────────────────


def mask(value: str | None) -> dict[str, Any]:
    """Public view of a secret: set + at most the last 4 characters."""
    v = (value or "").strip()
    if not v:
        return {"set": False, "hint": ""}
    return {"set": True, "hint": ("…" + v[-4:]) if len(v) >= 12 else ""}


def atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, mode)


def assert_safe_outbound_url(url: str) -> None:
    """Reject cloud-metadata / link-local targets (admin SSRF hardening).

    Localhost and RFC1918 remain allowed so a self-hosted LLM on LAN works.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as exc:
        raise ValidationError(f"invalid URL: {exc}", code="invalid_url") from exc
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("URL must start with http:// or https://", code="invalid_url")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValidationError("URL host is required", code="invalid_url")
    if host in _BLOCKED_HOSTS or host.endswith(".metadata.google.internal"):
        raise ValidationError("URL host is not allowed", code="forbidden_url")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Hostname: resolve and re-check (best-effort; DNS rebinding still possible).
        try:
            infos = socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)
        except OSError:
            return
        for info in infos:
            try:
                addr = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError):
                continue
            if addr.is_link_local or (addr.version == 4 and addr in ipaddress.ip_network("169.254.0.0/16")):
                raise ValidationError("URL host is not allowed", code="forbidden_url")
            if addr.version == 6 and addr in ipaddress.ip_network("fd00:ec2::/32"):
                raise ValidationError("URL host is not allowed", code="forbidden_url")
        return
    if addr.is_link_local or (addr.version == 4 and addr in ipaddress.ip_network("169.254.0.0/16")):
        raise ValidationError("URL host is not allowed", code="forbidden_url")
    if addr.version == 6 and addr in ipaddress.ip_network("fd00:ec2::/32"):
        raise ValidationError("URL host is not allowed", code="forbidden_url")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-check each redirect hop (blocks metadata/link-local bounce-off)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        try:
            assert_safe_outbound_url(newurl)
        except ValidationError as exc:
            raise urllib.error.HTTPError(
                newurl, 403, str(exc), headers, None
            ) from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen_safe(req: urllib.request.Request, *, timeout: float = 6.0):
    """``urlopen`` that re-validates redirect targets with ``assert_safe_outbound_url``."""
    assert_safe_outbound_url(req.full_url)
    opener = urllib.request.build_opener(_SafeRedirectHandler)
    return opener.open(req, timeout=timeout)  # noqa: S310 (admin URL, gated)


def http_get_json(url: str, key: str = "", timeout: float = 6.0) -> tuple[int, Any]:
    """GET ``url`` with an optional Bearer key → (status, json|None). Never logs the key."""
    try:
        assert_safe_outbound_url(url)
    except ValidationError as exc:
        return 0, {"error": exc.code or "forbidden_url"}
    req = urllib.request.Request(url, method="GET")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urlopen_safe(req, timeout=timeout) as resp:
            body = resp.read(2_000_000)
            try:
                return resp.status, json.loads(body.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, OSError, ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            return 0, {"error": exc.code or "forbidden_url"}
        reason = getattr(exc, "reason", exc)
        return 0, {"error": str(reason)[:200]}


def list_remote_models(base_url: str, key: str, timeout: float = 6.0) -> dict[str, Any]:
    base = (base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"ok": False, "status": 0, "error": "invalid_url", "models": []}
    try:
        assert_safe_outbound_url(base)
    except ValidationError as exc:
        return {"ok": False, "status": 0, "error": exc.code or "forbidden_url", "models": []}
    status, data = http_get_json(f"{base}/models", key, timeout=timeout)
    if status != 200:
        err = "unauthorized" if status in (401, 403) else (
            (data or {}).get("error") if isinstance(data, dict) and status == 0 else f"http_{status}"
        )
        return {"ok": False, "status": status, "error": err or "unreachable", "models": []}
    ids: list[str] = []
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        for row in data["data"]:
            if isinstance(row, dict) and row.get("id"):
                ids.append(str(row["id"]))
    return {"ok": True, "status": 200, "error": "", "models": ids}


# ── Pi LLM provider (~/.pi/agent/models.json) ─────────────────────────────


def pi_agent_dir() -> Path:
    return Path.home() / ".pi" / "agent"


def models_json_path() -> Path:
    return pi_agent_dir() / "models.json"


def _read_models_json() -> dict[str, Any]:
    path = models_json_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"models.json is not valid JSON: {exc}", code="models_json_invalid")
    return data if isinstance(data, dict) else {}


def resolve_api_key(raw: str | None) -> tuple[str, str]:
    """Pi apiKey semantics → (value, source). source: literal | env:NAME | command | none."""
    from autonomous.services.pi_status import pi_env

    v = (raw or "").strip()
    if not v:
        return "", "none"
    if v.startswith("!"):
        return "", "command"
    if _ENV_NAME.match(v):
        env = pi_env()
        if env.get(v):
            return env[v].strip(), f"env:{v}"
        # Pi would treat an unknown NAME as a literal key.
    return v, "literal"


def _int_or_none(raw: Any, *, lo: int | None = None, hi: int | None = None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def _model_public(entry: dict[str, Any]) -> dict[str, Any]:
    """UI-safe view of one Pi models.json model entry."""
    inp = entry.get("input") or ["text"]
    if not isinstance(inp, list):
        inp = ["text"]
    limits = entry.get("inputLimits") if isinstance(entry.get("inputLimits"), dict) else {}
    images_lim = limits.get("images") if isinstance(limits.get("images"), dict) else {}
    max_images = _int_or_none(images_lim.get("maxPerRequest"), lo=1, hi=32)
    if max_images is None:
        max_images = _int_or_none(images_lim.get("maxPerMessage"), lo=1, hi=32)
    return {
        "id": str(entry.get("id") or ""),
        "name": str(entry.get("name") or ""),
        "images": "image" in inp,
        "max_images": max_images,
        "context_window": _int_or_none(entry.get("contextWindow"), lo=1024, hi=2_000_000),
        "max_tokens": _int_or_none(entry.get("maxTokens"), lo=256, hi=512_000),
    }


def _patch_model_entry(entry: dict[str, Any], patch: dict[str, Any]) -> None:
    """Merge-safe patch of Pi model fields; never drops unknown keys (cost, compat…)."""
    if "name" in patch or "model_name" in patch:
        name = str(patch.get("name") if "name" in patch else patch.get("model_name") or "").strip()
        if name:
            entry["name"] = name
        else:
            entry.pop("name", None)

    if "images" in patch:
        images = bool(patch.get("images"))
        raw_inp = entry.get("input")
        inp = [x for x in (raw_inp if isinstance(raw_inp, list) else ["text"]) if x in ("text", "image")]
        if "text" not in inp:
            inp.insert(0, "text")
        if images and "image" not in inp:
            inp.append("image")
        if not images:
            inp = [x for x in inp if x != "image"]
        entry["input"] = inp or ["text"]

    if "max_images" in patch:
        max_images = _int_or_none(patch.get("max_images"), lo=1, hi=32)
        limits = entry.get("inputLimits")
        limits = dict(limits) if isinstance(limits, dict) else {}
        images_lim = limits.get("images")
        images_lim = dict(images_lim) if isinstance(images_lim, dict) else {}
        if max_images is None:
            images_lim.pop("maxPerRequest", None)
            images_lim.pop("maxPerMessage", None)
        else:
            images_lim["maxPerRequest"] = max_images
            msg_cap = _int_or_none(images_lim.get("maxPerMessage"), lo=1, hi=32)
            if msg_cap is None or msg_cap > max_images:
                images_lim["maxPerMessage"] = max_images
        if images_lim:
            limits["images"] = images_lim
        else:
            limits.pop("images", None)
        if limits:
            entry["inputLimits"] = limits
        else:
            entry.pop("inputLimits", None)

    if "context_window" in patch:
        cw = _int_or_none(patch.get("context_window"), lo=1024, hi=2_000_000)
        if cw is None:
            entry.pop("contextWindow", None)
        else:
            entry["contextWindow"] = cw

    if "max_tokens" in patch:
        mt = _int_or_none(patch.get("max_tokens"), lo=256, hi=512_000)
        if mt is None:
            entry.pop("maxTokens", None)
        else:
            entry["maxTokens"] = mt


def split_model_ref(ref: str | None) -> tuple[str, str]:
    raw = str(ref or "").strip()
    if not raw:
        return "", ""
    if "/" in raw:
        provider, _, model_id = raw.partition("/")
        return provider.strip(), model_id.strip()
    return "", raw


def find_model_entry(
    data: dict[str, Any],
    provider: str,
    model_id: str,
) -> dict[str, Any] | None:
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    conf = providers.get(provider) if provider else None
    if isinstance(conf, dict):
        for m in conf.get("models") or []:
            if isinstance(m, dict) and str(m.get("id") or "") == model_id:
                return m
    # Fallback: scan all providers when ref had no provider prefix.
    if not provider and model_id:
        for conf in providers.values():
            if not isinstance(conf, dict):
                continue
            for m in conf.get("models") or []:
                if isinstance(m, dict) and str(m.get("id") or "") == model_id:
                    return m
    overrides = data.get("modelOverrides") if isinstance(data.get("modelOverrides"), dict) else {}
    ov = overrides.get(model_id)
    return ov if isinstance(ov, dict) else None


def resolve_model_limits(ref: str | None) -> dict[str, Any]:
    """Limits from Pi models.json for ``provider/id`` (empty fields = unset)."""
    provider, model_id = split_model_ref(ref)
    if not model_id:
        return {"max_images": None, "context_window": None, "max_tokens": None, "name": ""}
    try:
        data = _read_models_json()
    except ValidationError:
        return {"max_images": None, "context_window": None, "max_tokens": None, "name": ""}
    entry = find_model_entry(data, provider, model_id)
    if not entry:
        # modelOverrides-only (built-in catalog)
        overrides = data.get("modelOverrides") if isinstance(data.get("modelOverrides"), dict) else {}
        entry = overrides.get(model_id) if isinstance(overrides.get(model_id), dict) else None
    if not entry:
        return {"max_images": None, "context_window": None, "max_tokens": None, "name": ""}
    pub = _model_public({**entry, "id": model_id})
    return {
        "max_images": pub["max_images"],
        "context_window": pub["context_window"],
        "max_tokens": pub["max_tokens"],
        "name": pub["name"],
    }


def remember_model_image_limit(ref: str | None, limit: int) -> None:
    """Persist a learned provider vision cap into Pi models.json (merge-safe)."""
    provider, model_id = split_model_ref(ref)
    if not model_id:
        return
    n = _int_or_none(limit, lo=1, hi=32)
    if n is None:
        return
    data = _read_models_json()
    entry = find_model_entry(data, provider, model_id)
    if entry is None:
        # Create override for built-in ids so we don't invent a fake provider.
        if not provider:
            overrides = data.get("modelOverrides")
            if not isinstance(overrides, dict):
                overrides = {}
            ov = dict(overrides.get(model_id) or {}) if isinstance(overrides.get(model_id), dict) else {}
            _patch_model_entry(ov, {"max_images": n})
            overrides[model_id] = ov
            data["modelOverrides"] = overrides
            atomic_write(models_json_path(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            return
        return
    _patch_model_entry(entry, {"max_images": n})
    atomic_write(models_json_path(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def llm_providers() -> list[dict[str, Any]]:
    """Providers from models.json with masked keys (no secret values)."""
    data = _read_models_json()
    out: list[dict[str, Any]] = []
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else {}
    for name, conf in providers.items():
        if not isinstance(conf, dict):
            continue
        value, source = resolve_api_key(conf.get("apiKey"))
        models = []
        for m in conf.get("models") or []:
            if isinstance(m, dict) and m.get("id"):
                models.append(_model_public(m))
        out.append(
            {
                "provider": name,
                "base_url": str(conf.get("baseUrl") or ""),
                "api": str(conf.get("api") or ""),
                "api_key": {**mask(value), "source": source},
                "models": models,
            }
        )
    return out


def llm_view() -> dict[str, Any]:
    provs = llm_providers()
    primary = provs[0] if provs else None
    return {
        "path": "~/.pi/agent/models.json",
        "providers": provs,
        "primary": primary,
        "docs": {
            "models": "https://pi.dev/docs/latest/models",
            "configuration": "https://pi.dev/docs/latest/models-configuration",
        },
    }


def save_llm(body: dict[str, Any]) -> dict[str, Any]:
    """Create/update one OpenAI-compatible provider in models.json (merge-safe).

    Accepts either a ``models`` list (full list replace for that provider) or a
    legacy single ``model`` / ``model_name`` / ``images`` payload.
    """
    provider = str(body.get("provider") or DEFAULT_PROVIDER).strip()
    if not _PROVIDER_RE.match(provider):
        raise ValidationError("invalid provider id", code="invalid_provider")
    base = str(body.get("base_url") or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValidationError("base URL must start with http:// or https://", code="invalid_url")
    # Same SSRF gate as runtime calls (blocks cloud metadata / link-local;
    # localhost + RFC1918 stay allowed for self-hosted LAN LLMs).
    assert_safe_outbound_url(base)
    new_key = body.get("api_key")
    new_key = str(new_key).strip() if new_key is not None else ""

    data = _read_models_json()
    data.setdefault("$schema", "https://pi.dev/schemas/models.schema.json")
    providers = data.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    conf = providers.get(provider)
    conf = dict(conf) if isinstance(conf, dict) else {}
    conf["baseUrl"] = base
    conf.setdefault("api", PI_API)
    if new_key:
        conf["apiKey"] = new_key  # empty field = keep current value
    elif "apiKey" not in conf:
        conf["apiKey"] = "none"  # pi requires a key; local servers ignore it

    existing_models = [m for m in (conf.get("models") or []) if isinstance(m, dict) and m.get("id")]
    by_id = {str(m["id"]): dict(m) for m in existing_models}

    raw_models = body.get("models")
    if "models" in body and isinstance(raw_models, list):
        # Full list replace for that provider (may be empty — credentials-only create).
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in raw_models:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("id") or "").strip()
            if not mid or mid in seen:
                continue
            seen.add(mid)
            entry = by_id.get(mid) or {"id": mid}
            entry["id"] = mid
            patch: dict[str, Any] = {}
            if "name" in row or "model_name" in row:
                patch["name"] = row.get("name", row.get("model_name"))
            if "images" in row:
                patch["images"] = row.get("images")
            elif mid not in by_id:
                patch["images"] = True
            if "max_images" in row:
                patch["max_images"] = row.get("max_images")
            if "context_window" in row:
                patch["context_window"] = row.get("context_window")
            if "max_tokens" in row:
                patch["max_tokens"] = row.get("max_tokens")
            if patch:
                _patch_model_entry(entry, patch)
            ordered.append(entry)
        conf["models"] = ordered
    elif str(body.get("model") or "").strip():
        model_id = str(body.get("model") or "").strip()
        entry = by_id.get(model_id) or {"id": model_id}
        entry["id"] = model_id
        patch = {
            "images": body.get("images", True),
        }
        if "model_name" in body or "name" in body:
            patch["name"] = body.get("model_name", body.get("name"))
        if "max_images" in body:
            patch["max_images"] = body.get("max_images")
        if "context_window" in body:
            patch["context_window"] = body.get("context_window")
        if "max_tokens" in body:
            patch["max_tokens"] = body.get("max_tokens")
        _patch_model_entry(entry, patch)
        rest = [m for m in existing_models if str(m.get("id")) != model_id]
        conf["models"] = [entry, *rest]
    else:
        # Provider credentials only — keep existing models (or start empty).
        conf.setdefault("models", existing_models)

    rest = {k: v for k, v in providers.items() if k != provider}
    data["providers"] = {provider: conf, **rest}
    atomic_write(models_json_path(), json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return llm_view()


def test_llm(body: dict[str, Any]) -> dict[str, Any]:
    """Test base URL + key (typed, or the stored one when the field is empty)."""
    provider = str(body.get("provider") or DEFAULT_PROVIDER).strip()
    base = str(body.get("base_url") or "").strip()
    key = str(body.get("api_key") or "").strip()
    if not key:
        conf = (_read_models_json().get("providers") or {}).get(provider) or {}
        key, _ = resolve_api_key(conf.get("apiKey") if isinstance(conf, dict) else "")
        if not base and isinstance(conf, dict):
            base = str(conf.get("baseUrl") or "")
    return list_remote_models(base, key)


MODELS_TIMEOUT = 10.0


def _is_masked(key: str) -> bool:
    """Empty, or the masked placeholder the UI shows (``…1234`` / ``...1234``)."""
    k = (key or "").strip()
    return not k or k.startswith(("…", "..."))


def _models_error(r: dict[str, Any]) -> tuple[int, str, str]:
    """list_remote_models failure → (http status for our API, code, readable message)."""
    err, st = r.get("error") or "unreachable", r.get("status") or 0
    if err == "invalid_url":
        return 400, err, "Invalid base URL: it must start with http:// or https://."
    if err == "unauthorized":
        return 502, err, f"The server rejected the API key (HTTP {st})."
    if str(err).startswith("http_"):
        return 502, err, f"The server answered HTTP {st} on /models."
    low = str(err).lower()
    if "timed out" in low or "timeout" in low:
        return 504, "timeout", f"No answer within {int(MODELS_TIMEOUT)} s."
    return 502, "unreachable", f"Server not reachable: {err}"


def fetch_models(base_url: str, key: str) -> tuple[int, dict[str, Any]]:
    r = list_remote_models(base_url, key, timeout=MODELS_TIMEOUT)
    if r["ok"]:
        return 200, {"models": sorted(set(r["models"]))}
    status, code, msg = _models_error(r)
    # Never echo the key: the message only carries status / reason.
    if key and key in msg:
        msg = msg.replace(key, "***")
    return status, {"models": [], "code": code, "message": msg}


def llm_models(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """List ``<base_url>/models`` with the typed key, or the stored one if empty/masked."""
    body = dict(body or {})
    if _is_masked(str(body.get("api_key") or "")):
        body["api_key"] = ""
    provider = str(body.get("provider") or DEFAULT_PROVIDER).strip()
    base = str(body.get("base_url") or "").strip()
    key = str(body.get("api_key") or "").strip()
    if not key:
        conf = (_read_models_json().get("providers") or {}).get(provider) or {}
        key, _ = resolve_api_key(conf.get("apiKey") if isinstance(conf, dict) else "")
        if not base and isinstance(conf, dict):
            base = str(conf.get("baseUrl") or "")
    return fetch_models(base, key)


def grounding_models(body: dict[str, Any], home: Path | None = None) -> tuple[int, dict[str, Any]]:
    """Same for the UI-TARS grounder, stored token when empty/masked (verification uses the LLM)."""
    from autonomous.services import grounding as g_svc

    kind = str((body or {}).get("kind") or "grounder")
    if kind != "grounder":
        return 400, {"models": [], "code": "invalid_kind", "message": "kind must be grounder."}
    cfg = g_svc.grounder_config(home, ignore_enabled=True)
    url = str(body.get("url") or "").strip() or cfg["base_url"]
    token = str(body.get("token") or "")
    key = cfg["api_key"] if _is_masked(token) else token.strip()
    if not url:
        return 400, {"models": [], "code": "not_configured", "message": "Enter the URL first."}
    return fetch_models(url, key or "")


# ── Grounding (AUTONOMOUS_HOME/grounder.env) ─────────────────────────────

GROUNDING_FIELDS: dict[str, dict[str, Any]] = {
    "enabled": {"env": "AUTONOMOUS_GROUNDING_ENABLED", "secret": False},
    "grounder_url": {"env": "AUTONOMOUS_GROUNDER_URL", "secret": False},
    "grounder_model": {"env": "AUTONOMOUS_GROUNDER_MODEL", "secret": False},
    "grounder_token": {"env": "AUTONOMOUS_GROUNDER_TOKEN", "secret": True},
}


def grounder_env_path(home: Path | None = None) -> Path:
    return ensure_home(home) / "grounder.env"


def _read_env_file(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.is_file():
        return [], {}
    lines = path.read_text(encoding="utf-8").splitlines()
    vals: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        vals[k.strip()] = v.strip().strip("'").strip('"')
    return lines, vals


def _is_on(value: str) -> bool:
    return str(value).strip().lower() not in ("0", "false", "off", "no")


def grounding_view(home: Path | None = None) -> dict[str, Any]:
    from autonomous.services import grounding as g_svc

    _, file_vals = _read_env_file(grounder_env_path(home))
    g = g_svc.grounder_config(home, ignore_enabled=True)
    effective = {
        "grounder_url": g["base_url"],
        "grounder_model": g["model"],
        "grounder_token": g["api_key"],
    }
    fields: dict[str, Any] = {}
    for fid, spec in GROUNDING_FIELDS.items():
        env_name = spec["env"]
        if os.environ.get(env_name):
            source = "env"
        elif file_vals.get(env_name):
            source = "file"
        else:
            source = "default"
        if fid == "enabled":
            # No explicit flag: on only when a grounder URL is configured (fresh install ? off).
            raw = os.environ.get(env_name) or file_vals.get(env_name) or ("1" if g["base_url"] else "0")
            fields[fid] = {"value": _is_on(raw), "source": source, "readonly": source == "env"}
            continue
        val = effective[fid]
        if source == "default" and val:
            source = "fallback"  # e.g. legacy key name, TOKEN file or Pi env
        item = {"source": source, "readonly": source == "env", "env": env_name}
        if spec["secret"]:
            item.update(mask(val))
        else:
            item["value"] = val
        fields[fid] = item
    return {"path": "grounder.env", "fields": fields}


def save_grounding(body: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    path = grounder_env_path(home)
    lines, _ = _read_env_file(path)
    updates: dict[str, str | None] = {}
    for fid, spec in GROUNDING_FIELDS.items():
        if fid not in body or body[fid] is None:
            continue
        env_name = spec["env"]
        if os.environ.get(env_name):
            continue  # env override: read-only
        if fid == "enabled":
            updates[env_name] = "1" if bool(body[fid]) else "0"
            continue
        val = str(body[fid]).strip()
        if spec["secret"]:
            if not val:
                continue  # empty = keep current
        elif fid.endswith("_url"):
            val = val.rstrip("/")
            if val:
                assert_safe_outbound_url(val)
        if any(c in val for c in "\r\n"):
            raise ValidationError(f"{fid}: invalid value", code="invalid_value")
        updates[env_name] = val
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        key = raw.split("=", 1)[0].strip() if "=" in raw and not raw.strip().startswith("#") else ""
        if key in updates:
            if key not in seen and updates[key] != "":
                out.append(f"{key}={updates[key]}")
            seen.add(key)
            continue
        out.append(raw)
    for key, val in updates.items():
        if key not in seen and val != "":
            out.append(f"{key}={val}")
    if not lines:
        out.insert(0, "# Written by the Autonomous web settings (mode 600).")
    atomic_write(path, "\n".join(out).rstrip("\n") + "\n")
    return grounding_view(home)


def test_grounding(body: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    from autonomous.services import grounding as g_svc

    g = g_svc.grounder_config(home, ignore_enabled=True)
    res: dict[str, Any] = {}
    for kind, cfg in (("grounder", g),):
        url = str(body.get(f"{kind}_url") or "").strip() or cfg["base_url"]
        key = str(body.get(f"{kind}_token") or "").strip() or cfg["api_key"]
        model = str(body.get(f"{kind}_model") or "").strip() or cfg["model"]
        if not url:
            res[kind] = {"ok": False, "error": "not_configured", "models": []}
            continue
        r = list_remote_models(url, key)
        if r["ok"] and model and r["models"] and model not in r["models"]:
            r = {**r, "ok": False, "error": "model_not_served"}
        res[kind] = r
    return res
