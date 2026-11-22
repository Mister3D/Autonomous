"""Persist chat image attachments (paste) and convert them for Pi RPC."""

from __future__ import annotations

import base64
import os
import re
import uuid
from pathlib import Path
from typing import Any

from autonomous.paths import bot_dir, bot_pi_dir
from autonomous.services.errors import NotFound, ValidationError

_DATA_URL = re.compile(
    r"^data:(image/(?:png|jpeg|jpg|webp|gif));base64,([A-Za-z0-9+/=\s]+)$",
    re.IGNORECASE | re.DOTALL,
)
_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Pasted images kept in the chat. The model receives a smaller copy (vision_fit).
MAX_IMAGE_ATTACHMENTS = 16
MAX_BYTES = 100 * 1024 * 1024
_IMAGE_FILE_EXTS = frozenset(_MIME_BY_EXT.keys())


def max_images_per_prompt(
    *,
    home: Path | None = None,
    bot: str | None = None,
    model_ref: str | None = None,
) -> int:
    """LLM vision budget for one prompt.

    Prefers Pi ``models.json`` ``inputLimits.images.maxPerRequest`` for the
    bot's model (solid Autonomous enforcement until Pi applies it itself).
    Falls back to ``guard.max_images_per_prompt`` (default 2).
    """
    from autonomous.services import bots as bots_svc
    from autonomous.services import settings as settings_svc
    from autonomous.services import setup_config as cfg_svc

    ref = (model_ref or "").strip()
    if not ref and bot:
        try:
            ref = str((bots_svc.get_bot(bot, home=home) or {}).get("model") or "")
        except Exception:
            ref = ""
    if ref:
        lim = cfg_svc.resolve_model_limits(ref).get("max_images")
        if lim is not None:
            cap = max(1, min(32, int(lim)))
            return _tighten_vision_cap(cap, bot, home=home)

    raw = settings_svc.get("guard.max_images_per_prompt", home=home, default=2)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 2
    cap = max(1, min(8, n))
    return _tighten_vision_cap(cap, bot, home=home)


def _tighten_vision_cap(cap: int, bot: str | None, *, home: Path | None) -> int:
    learned = read_vision_cap(bot, home=home) if bot else None
    if learned is None:
        return cap
    return min(cap, learned)


def vision_cap_path(bot: str, home: Path | None = None) -> Path:
    return bot_pi_dir(bot, home) / "vision_image_cap"


def read_vision_cap(bot: str | None, *, home: Path | None = None) -> int | None:
    """Tighter limit learned from a provider 'At most N image(s)' error."""
    if not bot:
        return None
    try:
        n = int(vision_cap_path(bot, home).read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return None
    if n < 1 or n > 32:
        return None
    return n


def write_vision_cap(bot: str, limit: int, *, home: Path | None = None) -> None:
    n = max(1, min(32, int(limit)))
    path = vision_cap_path(bot, home)
    path.write_text(str(n), encoding="utf-8")


def note_provider_image_limit(
    bot: str,
    model_ref: str | None,
    limit: int,
    *,
    home: Path | None = None,
) -> None:
    """Remember a provider image cap for the next request and the next Pi start."""
    from autonomous.services import settings as settings_svc

    write_vision_cap(bot, limit, home=home)
    try:
        from autonomous.services import setup_config as cfg_svc

        cfg_svc.remember_model_image_limit(model_ref or "", limit)
    except Exception:
        pass
    try:
        settings_svc.set_many({"guard.max_images_per_prompt": int(limit)}, home=home)
    except Exception:
        pass


def _chown_bot(path: Path) -> None:
    try:
        os.chown(path, 1000, 1000)
    except OSError:
        pass


def attachments_dir(bot: str, home: Path | None = None) -> Path:
    root = bot_dir(bot, home) / "home" / ".autonomous"
    root.mkdir(parents=True, exist_ok=True)
    _chown_bot(root)
    path = root / "chat-attachments"
    path.mkdir(parents=True, exist_ok=True)
    _chown_bot(path)
    return path


def _url(bot: str, att_id: str, ext: str) -> str:
    return f"/api/v1/bots/{bot}/chat/attachments/{att_id}{ext}"


def _parse_stored_url(bot: str, url: str) -> tuple[str, str] | None:
    prefix = f"/api/v1/bots/{bot}/chat/attachments/"
    if not url.startswith(prefix):
        return None
    name = url[len(prefix) :]
    if "/" in name or ".." in name:
        return None
    stem = Path(name).stem
    ext = Path(name).suffix.lower()
    if not stem or ext not in _MIME_BY_EXT:
        return None
    return stem, ext


def save_data_url(bot: str, data_url: str, *, home: Path | None = None) -> str:
    m = _DATA_URL.match((data_url or "").strip())
    if not m:
        raise ValidationError("Invalid image attachment (expected data:image/…;base64,…)")
    mime = m.group(1).lower()
    if mime == "image/jpg":
        mime = "image/jpeg"
    try:
        raw = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=False)
    except Exception as exc:
        raise ValidationError("Invalid image base64") from exc
    if not raw:
        raise ValidationError("Empty image attachment")
    if len(raw) > MAX_BYTES:
        raise ValidationError(f"Image too large (max {MAX_BYTES // (1024 * 1024)} Mo)")
    ext = _EXT[mime]
    att_id = str(uuid.uuid4())
    path = attachments_dir(bot, home) / f"{att_id}{ext}"
    path.write_bytes(raw)
    _chown_bot(path)
    return _url(bot, att_id, ext)


def _normalize_file_ref(
    bot: str,
    item: dict[str, Any],
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Validate a chat file already stored under ~/files/upload/<uuid>/…"""
    from autonomous.services import files as files_svc

    name = str(item.get("name") or "").strip()
    rel = str(item.get("path") or "").strip().replace("\\", "/")
    if not name or not rel:
        raise ValidationError("File attachment requires name and path")
    if ".." in rel.split("/") or rel.startswith("/"):
        raise ValidationError("Invalid file attachment path")
    if not rel.startswith(f"{files_svc.CHAT_UPLOAD_DIR}/"):
        raise ValidationError("File attachment must be under upload/")
    path = files_svc.resolve(bot, rel, home=home)
    if not path.is_file():
        raise NotFound("Attachment file not found")
    from urllib.parse import quote

    safe_name = path.name
    return {
        "type": "file",
        "name": name or safe_name,
        "path": rel,
        "url": f"/api/v1/bots/{bot}/files/download?path={quote(rel, safe='/')}",
        "size": path.stat().st_size,
    }


def normalize_attachments(
    bot: str,
    attachments: list[Any] | None,
    *,
    home: Path | None = None,
) -> list[Any]:
    """Normalize pasted images (URLs) and chat files (dicts under ~/files/upload/)."""
    raw = list(attachments or [])
    out: list[Any] = []
    image_count = 0
    for item in raw:
        if isinstance(item, dict):
            kind = str(item.get("type") or "file").lower()
            if kind != "file":
                raise ValidationError(f"Unsupported attachment type: {kind}")
            out.append(_normalize_file_ref(bot, item, home=home))
            continue
        s = str(item or "").strip()
        if not s:
            continue
        if s.startswith("data:image/"):
            if image_count >= MAX_IMAGE_ATTACHMENTS:
                raise ValidationError(
                    f"Too many images (max {MAX_IMAGE_ATTACHMENTS})"
                )
            out.append(save_data_url(bot, s, home=home))
            image_count += 1
            continue
        parsed = _parse_stored_url(bot, s)
        if parsed:
            if image_count >= MAX_IMAGE_ATTACHMENTS:
                raise ValidationError(
                    f"Too many images (max {MAX_IMAGE_ATTACHMENTS})"
                )
            stem, ext = parsed
            path = attachments_dir(bot, home) / f"{stem}{ext}"
            if not path.is_file():
                raise NotFound("Attachment not found")
            out.append(_url(bot, stem, ext))
            image_count += 1
            continue
        raise ValidationError("Unsupported attachment (paste an image or attach a file)")
    return out


def file_attachments(attachments: list[Any] | None) -> list[dict[str, Any]]:
    return [
        a
        for a in (attachments or [])
        if isinstance(a, dict) and str(a.get("type") or "").lower() == "file"
    ]


def image_attachments(attachments: list[Any] | None) -> list[str]:
    return [a for a in (attachments or []) if isinstance(a, str)]


def prompt_with_files(
    content: str,
    attachments: list[Any] | None,
    *,
    bot: str | None = None,
    home: Path | None = None,
) -> str:
    """Append absolute paths so the host-side Pi agent can open chat uploads.

    Never use ``~/files`` here: Pi runs as the host user (often root), so
    ``~`` expands to that user's home and gives ENOENT. Files live on the host under
    ``data/bots/<bot>/home/`` (= ``/home/autonomous/files`` inside the VM).
    """
    files = file_attachments(attachments)
    base = (content or "").strip()
    if not files:
        return base
    lines = [
        "Fichiers joints (chemins absolus — ne pas expandre ~) :",
    ]
    for f in files:
        name = f.get("name") or Path(str(f.get("path") or "")).name
        rel = str(f.get("path") or "").strip().replace("\\", "/")
        # workspace is the shell cwd and the same private folder as ~/files.
        vm_path = f"/home/autonomous/workspace/{rel}" if rel else ""
        host_path = ""
        if bot and rel:
            try:
                from autonomous.services import files as files_svc

                host_path = str(files_svc.resolve(bot, rel, home=home))
            except Exception:
                host_path = ""
        if host_path and vm_path:
            lines.append(
                f"- {name}\n"
                f"  • hôte (lecture fichiers Pi) : {host_path}\n"
                f"  • VM (vm_terminal_exec, dossier privé ~/files) : {vm_path}"
            )
        elif host_path:
            lines.append(f"- {name} → {host_path}")
        elif vm_path:
            lines.append(f"- {name} → {vm_path}")
        else:
            lines.append(f"- {name}")
    block = "\n".join(lines)
    return f"{base}\n\n{block}".strip() if base else block


def resolve_file(bot: str, filename: str, *, home: Path | None = None) -> Path:
    name = Path(filename).name
    if name != filename or ".." in name:
        raise NotFound("Attachment not found")
    path = (attachments_dir(bot, home) / name).resolve()
    root = attachments_dir(bot, home).resolve()
    if not str(path).startswith(str(root) + os.sep) and path != root:
        raise NotFound("Attachment not found")
    if not path.is_file():
        raise NotFound("Attachment not found")
    return path


def _pi_image(path: Path, mime: str) -> dict[str, Any] | None:
    """Image block for the model. The chat file stays at full size."""
    from autonomous.services.vision_fit import fit_image_path

    fitted = fit_image_path(path, mime)
    if fitted is None:
        return None
    data, out_mime = fitted
    return {
        "type": "image",
        "data": base64.b64encode(data).decode("ascii"),
        "mimeType": out_mime,
    }


def collect_vision_candidates(
    bot: str,
    attachments: list[Any] | None,
    *,
    home: Path | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Ordered (label, ImageContent) from pasted URLs then uploaded image files."""
    from autonomous.services import files as files_svc

    out: list[tuple[str, dict[str, Any]]] = []
    for url in image_attachments(attachments):
        parsed = _parse_stored_url(bot, url)
        if not parsed:
            continue
        stem, ext = parsed
        path = attachments_dir(bot, home) / f"{stem}{ext}"
        if not path.is_file():
            continue
        image = _pi_image(path, _MIME_BY_EXT[ext])
        if image is None:
            continue
        out.append((path.name, image))
    for f in file_attachments(attachments):
        rel = str(f.get("path") or "").strip().replace("\\", "/")
        name = str(f.get("name") or Path(rel).name)
        ext = Path(name).suffix.lower()
        if ext not in _IMAGE_FILE_EXTS:
            continue
        try:
            path = files_svc.resolve(bot, rel, home=home)
        except Exception:
            continue
        if not path.is_file():
            continue
        image = _pi_image(path, _MIME_BY_EXT[ext])
        if image is None:
            continue
        out.append((name, image))
    return out


def images_for_pi(
    bot: str,
    attachments: list[Any] | None,
    *,
    home: Path | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Pi ImageContent list capped to the LLM vision budget."""
    cap = (
        max_images_per_prompt(home=home, bot=bot)
        if limit is None
        else max(1, int(limit))
    )
    return [img for _, img in collect_vision_candidates(bot, attachments, home=home)[:cap]]


def apply_vision_budget(
    bot: str,
    content: str,
    attachments: list[Any] | None,
    *,
    home: Path | None = None,
    limit: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Return (prompt, images) respecting the Pi model vision budget.

    Extra images stay available as file paths in the prompt; the agent must
    continue in later turns instead of stuffing them all into one vision call.
    """
    cap = (
        max_images_per_prompt(home=home, bot=bot)
        if limit is None
        else max(1, int(limit))
    )
    candidates = collect_vision_candidates(bot, attachments, home=home)
    chosen = candidates[:cap]
    deferred = candidates[cap:]
    images = [img for _, img in chosen]
    text = (content or "").strip()
    if not deferred and not chosen:
        return text, images
    notes: list[str] = []
    if chosen:
        names = ", ".join(n for n, _ in chosen)
        notes.append(
            f"Images jointes à ce tour (vision, max {cap}/prompt) : {names}."
        )
    if deferred:
        names = ", ".join(n for n, _ in deferred)
        notes.append(
            f"Images restantes (à traiter dans un tour suivant, "
            f"sans dépasser {cap} images vision/prompt) : {names}."
        )
    block = "\n".join(notes)
    return (f"{text}\n\n{block}".strip() if text else block), images


def parse_provider_image_limit(error: str) -> int | None:
    """Extract N from provider errors like 'At most 2 image(s) may be provided'."""
    m = re.search(
        r"at most\s+(\d+)\s+image",
        str(error or ""),
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return max(1, int(m.group(1)))
    except ValueError:
        return None
