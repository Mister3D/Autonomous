"""Detect Pi install, readiness, and available models."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


DOC_URL = "https://pi.dev/docs/latest/models"
LOCAL_DOC_PATH = "docs/features/pi-agent.md"

_LIST_HEADER = re.compile(r"^provider\s+model\b", re.I)
_QUANT_SUFFIX = re.compile(
    r"-(?:W\d+A\d+|AWQ|GPTQ|GGUF|Q\d+_K(?:_[A-Z]+)?|fp\d+|int\d+)$",
    re.I,
)


def _candidate_bins() -> list[Path]:
    found: list[Path] = []
    which = shutil.which("pi")
    if which:
        found.append(Path(which))
    local = Path.home() / ".local" / "bin" / "pi"
    if local.is_file() and local not in found:
        found.append(local)
    return found


def resolve_pi_bin() -> str | None:
    for path in _candidate_bins():
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def _load_pi_env_file() -> dict[str, str]:
    """Optional secrets file: ~/.pi/agent/env (KEY=VALUE lines)."""
    path = Path.home() / ".pi" / "agent" / "env"
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key:
                out[key] = value
    except OSError:
        return out
    return out


def pi_env() -> dict[str, str]:
    env = os.environ.copy()
    # File values fill gaps only — real process env wins.
    for key, value in _load_pi_env_file().items():
        env.setdefault(key, value)
    local_bin = str(Path.home() / ".local" / "bin")
    path = env.get("PATH", "")
    if local_bin not in path.split(":"):
        env["PATH"] = f"{local_bin}:{path}" if path else local_bin
    return env


def pi_version(bin_path: str | None = None) -> str | None:
    binary = bin_path or resolve_pi_bin()
    if not binary:
        return None
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            env=pi_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or proc.stderr or "").strip().splitlines()[0].strip() or None


def models_json_path() -> Path:
    return Path.home() / ".pi" / "agent" / "models.json"


def _names_from_models_json() -> dict[str, str]:
    """Map provider/id → display name from ~/.pi/agent/models.json."""
    path = models_json_path()
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, dict):
        return out
    for provider, conf in providers.items():
        if not isinstance(conf, dict):
            continue
        for entry in conf.get("models") or []:
            if not isinstance(entry, dict):
                continue
            mid = entry.get("id")
            name = entry.get("name")
            if mid and name:
                out[f"{provider}/{mid}"] = str(name)
                out[str(mid)] = str(name)
    return out


def _short_model_name(model_id: str) -> str:
    leaf = (model_id or "").split("/")[-1]
    # Drop trailing quant tags: …-W4A16-AWQ
    cleaned = leaf
    for _ in range(3):
        nxt = _QUANT_SUFFIX.sub("", cleaned)
        if nxt == cleaned:
            break
        cleaned = nxt
    # Prefer a compact title if still very long (org marketing slugs).
    if len(cleaned) > 36:
        parts = [p for p in cleaned.split("-") if p]
        # Keep first chunks that look like the model family + size.
        keep: list[str] = []
        for part in parts:
            keep.append(part)
            joined = "-".join(keep)
            if len(joined) >= 12 and any(ch.isdigit() for ch in part):
                break
            if len(keep) >= 3:
                break
        cleaned = "-".join(keep) if keep else cleaned[:36]
    return cleaned or model_id


def friendly_label(provider: str, model_id: str, *, names: dict[str, str] | None = None) -> str:
    names = names if names is not None else _names_from_models_json()
    ref = f"{provider}/{model_id}"
    if ref in names:
        return names[ref]
    if model_id in names:
        return names[model_id]
    short = _short_model_name(model_id)
    if provider and provider.lower() not in short.lower():
        return f"{short} · {provider}"
    return short


def list_models(bin_path: str | None = None) -> list[dict[str, Any]]:
    """Parse `pi --list-models` into [{provider, id, ref, label}, …]."""
    binary = bin_path or resolve_pi_bin()
    if not binary:
        return []
    try:
        proc = subprocess.run(
            [binary, "--list-models", "--offline"],
            capture_output=True,
            text=True,
            timeout=30,
            env=pi_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if "No models available" in text:
        return []
    names = _names_from_models_json()
    models: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = line.rstrip()
        if not raw.strip() or _LIST_HEADER.match(raw.strip()):
            continue
        if raw.strip().startswith("Use /login"):
            continue
        parts = raw.split()
        if len(parts) < 2:
            continue
        provider, model_id = parts[0], parts[1]
        if provider.lower() == "provider":
            continue
        models.append(
            {
                "provider": provider,
                "id": model_id,
                "ref": f"{provider}/{model_id}",
                "label": friendly_label(provider, model_id, names=names),
            }
        )
    return models


def status() -> dict[str, Any]:
    binary = resolve_pi_bin()
    installed = binary is not None
    version = pi_version(binary) if installed else None
    models = list_models(binary) if installed else []
    ready = bool(installed and models)
    reason = None
    if not installed:
        reason = "not_installed"
    elif not models:
        reason = "no_models"
    return {
        "installed": installed,
        "ready": ready,
        "reason": reason,
        "version": version,
        "bin": binary,
        "models_json": str(models_json_path()),
        "models_count": len(models),
        "doc_url": DOC_URL,
        "local_doc": LOCAL_DOC_PATH,
    }
