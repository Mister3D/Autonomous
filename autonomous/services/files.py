"""Bot file browsing under ~/files (host-mounted, private per bot)."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

from autonomous.i18n import t
from autonomous.paths import bot_dir
from autonomous.services import bots as bots_svc
from autonomous.services.errors import AutonomousError, Forbidden, NotFound, ValidationError
from autonomous.services.events import BUS

# Shown in the UI as ~/files — host path bots/<name>/home (one folder per bot).
# "shared" stays accepted so older paths and chat markdown still resolve.
FILES_LABEL = "files"
_FILES_ALIASES = ("files", "shared")
CHAT_UPLOAD_DIR = "upload"
MAIL_INBOX_DIR = ".autonomous/mail-inbox"
# Drag-and-drop / picker, in the Files tab and in the chat. Mail stays smaller.
MAX_CHAT_FILE_BYTES = 10 * 1024 * 1024 * 1024
MAX_MAIL_ATTACHMENTS = 10
MAX_MAIL_ATTACHMENT_BYTES = 50 * 1024 * 1024
MAX_MAIL_ATTACHMENTS_TOTAL_BYTES = 100 * 1024 * 1024

_SAFE_NAME = re.compile(r"^[^/\x00]{1,255}$")


def _notify_changed(
    bot: str,
    *,
    op: str,
    path: str = "",
    is_dir: bool | None = None,
) -> None:
    """Push a Files-tab refresh hint (SSE + BroadcastChannel)."""
    payload: dict[str, Any] = {"bot": bot, "op": op, "path": path or ""}
    if is_dir is not None:
        payload["is_dir"] = bool(is_dir)
    BUS.publish("files.changed", payload, bot=bot)


def _root(bot: str, home: Path | None) -> Path:
    bots_svc.get_bot(bot, home=home)
    root = (bot_dir(bot, home) / "home").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _strip_files_alias(rel: str) -> str:
    """Drop ~/files or the legacy ~/shared prefix. Empty string means the root."""
    rel = (rel or "").replace("\\", "/").strip().lstrip("/")
    for name in _FILES_ALIASES:
        for prefix in (f"~/{name}/", f"{name}/", f"~/{name}", name):
            bare = prefix.rstrip("/")
            if rel == bare or rel.startswith(prefix if prefix.endswith("/") else prefix + "/"):
                if rel == bare:
                    return ""
                return rel[len(prefix) :].lstrip("/")
    return rel


def resolve(bot: str, rel: str, home: Path | None = None) -> Path:
    root = _root(bot, home)
    rel = _strip_files_alias(rel or ".")
    if not rel or rel == ".":
        return root
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Forbidden(t("files.forbidden")) from exc
    return target


def _dir_total_size(path: Path, *, max_entries: int = 50_000) -> int:
    """Sum file bytes under ``path`` (best-effort; capped for huge trees)."""
    total = 0
    seen = 0
    stack = [path]
    try:
        while stack:
            current = stack.pop()
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if entry.is_file(follow_symlinks=False):
                            seen += 1
                            if seen > max_entries:
                                return total
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
    except OSError:
        return total
    return total


def list_dir(bot: str, path: str = ".", home: Path | None = None) -> list[dict[str, Any]]:
    target = resolve(bot, path, home=home)
    if not target.exists():
        raise NotFound(t("files.not_found"))
    if not target.is_dir():
        raise NotFound(t("files.not_found"))
    entries: list[dict[str, Any]] = []
    root = _root(bot, home)
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        rel = str(child.relative_to(root)).replace(os.sep, "/")
        stat = child.stat()
        is_dir = child.is_dir()
        entries.append(
            {
                "name": child.name,
                "path": rel,
                "is_dir": is_dir,
                "size": _dir_total_size(child) if is_dir else stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        )
    return entries


# Text read/write for the agent (Pi files_* tools). Binary stays on download/upload.
MAX_TEXT_BYTES = 1_000_000

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".bmp": "image/bmp",
}


def image_mime(path: Path | str) -> str | None:
    return _IMAGE_MIME.get(Path(path).suffix.lower())


def share_image(
    bot: str,
    path: str,
    *,
    caption: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    """Validate a ~/files image and return markdown to paste into the assistant reply.

    The model can only emit text — embedding an image means writing ``![…](url)``
    in the reply body (rendered by the chat markdown). This helper builds that line.
    """
    target = resolve(bot, path, home=home)
    if not target.exists() or not target.is_file():
        raise NotFound(t("files.not_found"))
    mime = image_mime(target)
    if not mime:
        raise AutonomousError(
            "Not an image (allowed: png, jpg, webp, gif, svg, bmp).",
            code="not_an_image",
        )
    size = target.stat().st_size
    if size <= 0:
        raise AutonomousError("Empty file", code="empty_file")
    root = _root(bot, home)
    rel = str(target.relative_to(root)).replace(os.sep, "/")
    from urllib.parse import quote

    url = f"/api/v1/bots/{bot}/files/raw?path={quote(rel, safe='/')}"
    label = (caption or "").strip() or target.name
    # Escape ] in alt text so markdown stays valid.
    alt = label.replace("]", "")
    markdown = f"![{alt}]({url})"
    return {
        "ok": True,
        "path": rel,
        "name": target.name,
        "url": url,
        "mime": mime,
        "bytes": size,
        "caption": label,
        "markdown": markdown,
        "embedded": True,
    }


_MCP_IMAGE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
_MCP_IMAGE_MAGIC = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/gif": b"GIF8",
    "image/webp": b"RIFF",
    "image/bmp": b"BM",
}
MAX_MCP_IMAGE_BYTES = 100 * 1024 * 1024


def save_mcp_image(
    bot: str,
    mime: str,
    data_b64: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Write an MCP image (screenshot, photo) under ~/files/mcp and return share markdown."""
    kind = (mime or "").split(";", 1)[0].strip().lower()
    ext = _MCP_IMAGE_EXT.get(kind)
    magic = _MCP_IMAGE_MAGIC.get(kind)
    if not ext or not magic:
        raise ValidationError("Unsupported MCP image type")
    try:
        raw = base64.b64decode("".join((data_b64 or "").split()), validate=True)
    except Exception as exc:
        raise ValidationError("MCP image is not valid base64") from exc
    if not raw.startswith(magic):
        raise ValidationError("MCP image bytes do not match its type")
    if kind == "image/webp" and (len(raw) < 12 or raw[8:12] != b"WEBP"):
        raise ValidationError("MCP image bytes do not match its type")
    if len(raw) > MAX_MCP_IMAGE_BYTES:
        raise ValidationError("MCP image is too large")
    rel = f"mcp/{uuid.uuid4().hex}{ext}"
    target = resolve(bot, rel, home=home)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    try:
        os.chown(target, 1000, 1000)
    except OSError:
        pass
    _notify_changed(bot, op="upload", path=rel, is_dir=False)
    return share_image(bot, rel, caption="capture", home=home)


def attach_file(
    bot: str,
    path: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Attach a non-image file (PDF, zip, …) to the assistant reply as a download card."""
    from autonomous.services import chat as chat_svc
    from urllib.parse import quote

    target = resolve(bot, path, home=home)
    if not target.exists() or not target.is_file():
        raise NotFound(t("files.not_found"))
    if image_mime(target):
        raise AutonomousError(
            "Images belong inline in the reply — use files_share_image and paste the markdown. "
            "Attachments are for PDF, zip, and other non-preview files.",
            code="use_share_image",
        )
    size = target.stat().st_size
    if size <= 0:
        raise AutonomousError("Empty file", code="empty_file")
    root = _root(bot, home)
    rel = str(target.relative_to(root)).replace(os.sep, "/")
    url = f"/api/v1/bots/{bot}/files/download?path={quote(rel, safe='/')}"
    att = {
        "type": "file",
        "name": target.name,
        "path": rel,
        "url": url,
        "size": size,
        "source": "files_attach",
    }
    streaming = chat_svc.find_streaming_assistant(bot, home=home)
    if streaming:
        message = chat_svc.append_attachments(
            bot, streaming["id"], [att], home=home
        )
        mode = "attached"
    else:
        message = chat_svc.create_assistant_placeholder(bot, home=home)
        message = chat_svc.append_attachments(
            bot, message["id"], [att], home=home
        )
        mode = "assistant"
    return {
        "ok": True,
        "path": rel,
        "name": target.name,
        "url": url,
        "bytes": size,
        "message_id": message["id"],
        "mode": mode,
        "attached": True,
    }


def read_text(bot: str, path: str, home: Path | None = None) -> dict[str, Any]:
    """Read a UTF-8 text file under ~/files (agent-facing)."""
    target = resolve(bot, path, home=home)
    if not target.exists() or not target.is_file():
        raise NotFound(t("files.not_found"))
    size = target.stat().st_size
    if size > MAX_TEXT_BYTES:
        raise AutonomousError(
            f"File too large to read as text (max {MAX_TEXT_BYTES // 1000} KB). "
            "Use the Files panel download or split the file.",
            code="file_too_large",
        )
    raw = target.read_bytes()
    if b"\x00" in raw[:8192]:
        raise AutonomousError(
            "Binary file — use download / vm tools, not text read.",
            code="binary_file",
        )
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AutonomousError(
            "File is not valid UTF-8 text.",
            code="not_utf8",
        ) from exc
    root = _root(bot, home)
    rel = str(target.relative_to(root)).replace(os.sep, "/")
    return {
        "path": rel,
        "name": target.name,
        "size": size,
        "content": content,
        "encoding": "utf-8",
    }


def write_text(
    bot: str,
    path: str,
    content: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Create or overwrite a UTF-8 text file under ~/files (agent-facing)."""
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise AutonomousError("content must be a string", code="validation_error")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        raise AutonomousError(
            f"Content too large (max {MAX_TEXT_BYTES // 1000} KB).",
            code="file_too_large",
        )
    rel = (path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or rel in (".", "..") or ".." in rel.split("/"):
        raise AutonomousError("Invalid path", code="invalid_path")
    rel = _strip_files_alias(rel)
    if not rel or rel.endswith("/"):
        raise AutonomousError("Path must be a file path", code="invalid_path")
    parent_rel = str(Path(rel).parent).replace("\\", "/")
    if parent_rel in (".", ""):
        parent_rel = "."
    name = Path(rel).name
    safe = _safe_filename(name)
    directory = resolve(bot, parent_rel, home=home)
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise AutonomousError("Destination is not a directory", code="not_a_directory")
    target = (directory / safe).resolve()
    root = _root(bot, home)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Forbidden(t("files.forbidden")) from exc
    if target.exists() and target.is_dir():
        raise AutonomousError("Path is a directory", code="is_directory")
    if target.exists() and target.is_file():
        # Don't clobber images/binaries with accidental text writes (agent pitfall).
        existing = target.read_bytes()[:8192]
        if b"\x00" in existing or image_mime(target):
            raise AutonomousError(
                "Refusing to overwrite a binary/image file with text. "
                "Use a new path, or delete first with files_delete.",
                code="refuse_overwrite_binary",
            )
    target.write_bytes(encoded)
    try:
        os.chown(target, 1000, 1000)
    except OSError:
        pass
    entry = _entry_dict(root, target)
    _notify_changed(bot, op="write", path=entry["path"], is_dir=False)
    return entry


def delete_path(bot: str, path: str, home: Path | None = None) -> None:
    target = resolve(bot, path, home=home)
    root = _root(bot, home)
    if target == root:
        raise Forbidden(t("files.forbidden"))
    if not target.exists():
        raise NotFound(t("files.not_found"))
    try:
        rel = str(target.relative_to(root)).replace(os.sep, "/")
    except ValueError:
        rel = path or ""
    was_dir = target.is_dir()
    if was_dir:
        import shutil

        shutil.rmtree(target)
    else:
        target.unlink()
    _notify_changed(bot, op="delete", path=rel, is_dir=was_dir)


def _safe_filename(name: str) -> str:
    base = Path(name or "upload").name
    if not base or base in (".", "..") or not _SAFE_NAME.match(base):
        raise AutonomousError("Invalid filename", code="invalid_filename")
    return base


def _entry_dict(root: Path, target: Path) -> dict[str, Any]:
    stat = target.stat()
    rel = str(target.relative_to(root)).replace(os.sep, "/")
    is_dir = target.is_dir()
    return {
        "name": target.name,
        "path": rel,
        "is_dir": is_dir,
        "size": _dir_total_size(target) if is_dir else stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def move_path(
    bot: str,
    src: str,
    dest_dir: str = ".",
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Move a file or directory into ``dest_dir`` (same basename)."""
    root = _root(bot, home)
    source = resolve(bot, src, home=home)
    if source == root:
        raise Forbidden(t("files.forbidden"))
    if not source.exists():
        raise NotFound(t("files.not_found"))
    dest_parent = resolve(bot, dest_dir or ".", home=home)
    if not dest_parent.exists() or not dest_parent.is_dir():
        raise NotFound(t("files.not_found"))
    # Refuse moving a directory into itself or a descendant.
    try:
        source.resolve().relative_to(root)
        dest_parent.resolve().relative_to(root)
    except ValueError as exc:
        raise Forbidden(t("files.forbidden")) from exc
    if source.is_dir():
        try:
            dest_parent.resolve().relative_to(source.resolve())
            raise Forbidden(t("files.forbidden"))
        except ValueError:
            pass
    dest = dest_parent / source.name
    if dest.resolve() == source.resolve():
        return _entry_dict(root, source)
    if dest.exists():
        raise ValidationError(t("files.exists"), code="exists")
    shutil.move(str(source), str(dest))
    try:
        os.chown(dest, 1000, 1000)
    except OSError:
        pass
    entry = _entry_dict(root, dest)
    _notify_changed(bot, op="move", path=entry["path"], is_dir=entry["is_dir"])
    return entry


def mkdir(
    bot: str,
    parent: str,
    name: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Create a directory under ~/files."""
    directory = resolve(bot, parent or ".", home=home)
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise AutonomousError("Destination is not a directory", code="not_a_directory")
    safe = _safe_filename(name)
    target = (directory / safe).resolve()
    root = _root(bot, home)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Forbidden(t("files.forbidden")) from exc
    if target.exists():
        raise AutonomousError("Already exists", code="already_exists")
    target.mkdir(parents=False, exist_ok=False)
    try:
        os.chown(target, 1000, 1000)
    except OSError:
        pass
    entry = _entry_dict(root, target)
    _notify_changed(bot, op="mkdir", path=entry["path"], is_dir=True)
    return entry


def _size_label(n: int) -> str:
    if n >= 1024 ** 3 and n % (1024 ** 3) == 0:
        return f"{n // (1024 ** 3)} Go"
    return f"{n // (1024 * 1024)} Mo"


def _stream_to_file(stream: BinaryIO, target: Path, limit: int) -> int:
    """Copy ``stream`` onto ``target``. Over the limit, delete the partial file."""
    total = 0
    try:
        with open(target, "wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise AutonomousError(
                        f"File too large (max {_size_label(limit)})",
                        code="file_too_large",
                    )
                out.write(chunk)
    except AutonomousError:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return total


def save_upload(
    bot: str,
    dest_dir: str,
    *,
    filename: str,
    stream: BinaryIO,
    home: Path | None = None,
) -> dict[str, Any]:
    """Save an uploaded file into a directory under ~/files."""
    directory = resolve(bot, dest_dir or ".", home=home)
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise AutonomousError("Destination is not a directory", code="not_a_directory")
    safe = _safe_filename(filename)
    target = (directory / safe).resolve()
    root = _root(bot, home)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Forbidden(t("files.forbidden")) from exc
    _stream_to_file(stream, target, MAX_CHAT_FILE_BYTES)
    try:
        os.chown(target, 1000, 1000)
    except OSError:
        pass
    entry = _entry_dict(root, target)
    _notify_changed(bot, op="upload", path=entry["path"], is_dir=False)
    return entry


def save_chat_upload(
    bot: str,
    *,
    filename: str,
    stream: BinaryIO,
    home: Path | None = None,
) -> dict[str, Any]:
    """Save a chat attachment under ``~/files/upload/<uuid>/<original_name>``.

    UUID folder avoids collisions when the same display name is uploaded twice.
    The conversation keeps ``name`` (original); the bot reads via ``path``.
    """
    bots_svc.get_bot(bot, home=home)
    safe = _safe_filename(filename)
    folder_id = str(uuid.uuid4())
    rel_dir = f"{CHAT_UPLOAD_DIR}/{folder_id}"
    directory = resolve(bot, rel_dir, home=home)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chown(directory, 1000, 1000)
        os.chown(directory.parent, 1000, 1000)
    except OSError:
        pass
    target = (directory / safe).resolve()
    root = _root(bot, home)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Forbidden(t("files.forbidden")) from exc
    try:
        total = _stream_to_file(stream, target, MAX_CHAT_FILE_BYTES)
    except AutonomousError:
        try:
            directory.rmdir()
        except OSError:
            pass
        raise
    if total == 0:
        try:
            target.unlink(missing_ok=True)
            directory.rmdir()
        except OSError:
            pass
        raise AutonomousError("Empty file", code="empty_file")
    try:
        os.chown(target, 1000, 1000)
    except OSError:
        pass
    rel_path = f"{rel_dir}/{safe}".replace("\\", "/")
    _notify_changed(bot, op="upload", path=rel_path, is_dir=False)
    return {
        "type": "file",
        "name": safe,
        "path": rel_path,
        "url": f"/api/v1/bots/{bot}/files/download?path={quote(rel_path, safe='/')}",
        "size": total,
    }


def _unique_child(directory: Path, name: str) -> Path:
    """Return ``directory/name``, adding ``_2``, ``_3``… on collision."""
    safe = _safe_filename(name)
    candidate = directory / safe
    if not candidate.exists():
        return candidate
    stem = Path(safe).stem
    suffix = Path(safe).suffix
    n = 2
    while True:
        alt = directory / f"{stem}_{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1
        if n > 10_000:
            raise AutonomousError("Could not allocate unique filename", code="name_collision")


def stage_mail_attachments(
    from_bot: str,
    to_bot: str,
    paths: list[str],
    *,
    inbox_id: str,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    """Copy sender ``~/files`` files into the recipient mail-inbox staging area.

    Staging path: ``.autonomous/mail-inbox/<inbox_id>/<filename>``.
    The recipient may then claim/move them wherever they want.
    """
    if not paths:
        return []
    if len(paths) > MAX_MAIL_ATTACHMENTS:
        raise ValidationError(
            f"Too many attachments (max {MAX_MAIL_ATTACHMENTS})",
            code="mail_too_many_attachments",
        )
    inbox_id = (inbox_id or "").strip()
    if not inbox_id or "/" in inbox_id or ".." in inbox_id:
        raise ValidationError("Invalid inbox id", code="invalid_inbox_id")

    bots_svc.get_bot(from_bot, home=home)
    bots_svc.get_bot(to_bot, home=home)
    dest_root = resolve(to_bot, f"{MAIL_INBOX_DIR}/{inbox_id}", home=home)
    dest_root.mkdir(parents=True, exist_ok=True)
    try:
        # Own as desktop user when possible (bind-mount).
        os.chown(dest_root, 1000, 1000)
        for parent in (dest_root.parent, dest_root.parent.parent):
            try:
                os.chown(parent, 1000, 1000)
            except OSError:
                pass
    except OSError:
        pass

    staged: list[dict[str, Any]] = []
    total = 0
    try:
        for raw in paths:
            rel = (raw or "").strip()
            if not rel:
                raise ValidationError("Empty attachment path", code="mail_empty_path")
            src = resolve(from_bot, rel, home=home)
            if not src.is_file():
                raise NotFound(
                    f"Attachment not found: {rel}",
                    code="mail_attachment_missing",
                )
            size = src.stat().st_size
            if size <= 0:
                raise ValidationError(
                    f"Empty attachment: {rel}",
                    code="mail_empty_file",
                )
            if size > MAX_MAIL_ATTACHMENT_BYTES:
                raise ValidationError(
                    f"Attachment too large (max {MAX_MAIL_ATTACHMENT_BYTES // (1024 * 1024)} Mo): {rel}",
                    code="mail_file_too_large",
                )
            total += size
            if total > MAX_MAIL_ATTACHMENTS_TOTAL_BYTES:
                raise ValidationError(
                    f"Attachments total too large (max {MAX_MAIL_ATTACHMENTS_TOTAL_BYTES // (1024 * 1024)} Mo)",
                    code="mail_total_too_large",
                )
            target = _unique_child(dest_root, src.name)
            shutil.copy2(src, target)
            try:
                os.chown(target, 1000, 1000)
            except OSError:
                pass
            digest = hashlib.sha256()
            with open(target, "rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            dest_rel = str(target.relative_to(_root(to_bot, home))).replace(os.sep, "/")
            source_rel = str(src.relative_to(_root(from_bot, home))).replace(os.sep, "/")
            staged.append(
                {
                    "name": target.name,
                    "path": dest_rel,
                    "source_path": source_rel,
                    "size": size,
                    "sha256": digest.hexdigest(),
                    "url": (
                        f"/api/v1/bots/{to_bot}/files/download"
                        f"?path={quote(dest_rel, safe='/')}"
                    ),
                }
            )
    except Exception:
        # Roll back partial staging for this inbox id.
        try:
            shutil.rmtree(dest_root, ignore_errors=True)
        except Exception:
            pass
        raise

    _notify_changed(to_bot, op="mail_stage", path=f"{MAIL_INBOX_DIR}/{inbox_id}", is_dir=True)
    return staged


def claim_mail_attachment(
    bot: str,
    staging_path: str,
    dest: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Move a staged mail-inbox file to ``dest`` under the bot's ``~/files``."""
    src_rel = _strip_files_alias(staging_path or "")
    if not src_rel.startswith(f"{MAIL_INBOX_DIR}/"):
        raise ValidationError(
            f"path must be under {MAIL_INBOX_DIR}/",
            code="mail_not_staging",
        )
    src = resolve(bot, src_rel, home=home)
    if not src.is_file():
        raise NotFound(t("files.not_found"))

    dest_rel = _strip_files_alias(dest or "")
    if not dest_rel or dest_rel in (".", "..") or ".." in dest_rel.split("/"):
        raise ValidationError("Invalid destination path", code="invalid_path")
    if dest_rel.endswith("/"):
        raise ValidationError("Destination must be a file path", code="invalid_path")
    if dest_rel.startswith(f"{MAIL_INBOX_DIR}/"):
        raise ValidationError(
            "Destination must be outside the mail staging area",
            code="mail_dest_staging",
        )

    parent_rel = str(Path(dest_rel).parent).replace("\\", "/")
    if parent_rel in (".", ""):
        parent_rel = "."
    name = Path(dest_rel).name
    safe = _safe_filename(name)
    directory = resolve(bot, parent_rel, home=home)
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir():
        raise AutonomousError("Destination is not a directory", code="not_a_directory")
    target = (directory / safe).resolve()
    root = _root(bot, home)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise Forbidden(t("files.forbidden")) from exc
    if target.exists():
        raise AutonomousError("Destination already exists", code="already_exists")

    shutil.move(str(src), str(target))
    try:
        os.chown(target, 1000, 1000)
    except OSError:
        pass
    # Drop empty staging folders.
    try:
        parent = src.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            grand = parent.parent
            if (
                grand.is_dir()
                and grand.name == "mail-inbox"
                and not any(grand.iterdir())
            ):
                pass  # keep mail-inbox dir
    except OSError:
        pass

    entry = _entry_dict(root, target)
    _notify_changed(bot, op="mail_claim", path=entry["path"], is_dir=False)
    _notify_changed(bot, op="delete", path=src_rel, is_dir=False)
    return entry
