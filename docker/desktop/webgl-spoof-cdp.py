#!/usr/bin/env python3
"""Inject WebGL vendor/renderer spoof early on every page via Chrome CDP."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

try:
    import websockets
except ImportError:
    print("python3-websockets required", file=sys.stderr)
    raise SystemExit(1)

log = logging.getLogger("webgl-spoof")

DEFAULT_VENDOR = "Google Inc. (Intel)"
DEFAULT_RENDERER = (
    "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)"
)
CALL_TIMEOUT = 20.0


def load_script(vendor: str, renderer: str) -> str:
    candidates = [
        Path("/usr/local/share/autonomous/webgl-spoof.js"),
        Path(__file__).with_name("webgl-spoof.js"),
    ]
    src = None
    for path in candidates:
        if path.exists():
            src = path.read_text(encoding="utf-8")
            break
    if src is None:
        raise FileNotFoundError("webgl-spoof.js not found")
    return src.replace('"__WEBGL_VENDOR__"', json.dumps(vendor)).replace(
        '"__WEBGL_RENDERER__"', json.dumps(renderer)
    )


def debugger_url(port: int) -> str | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
            data = json.load(resp)
        return data.get("webSocketDebuggerUrl")
    except Exception:
        return None


class CdpClient:
    def __init__(self, ws, script: str):
        self.ws = ws
        self.script = script
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._spoofed: set[str] = set()  # targetIds already spoofed
        self._spoof_lock = asyncio.Lock()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def call(
        self,
        method: str,
        params: dict | None = None,
        session_id: str | None = None,
        *,
        timeout: float = CALL_TIMEOUT,
    ):
        msg: dict = {"id": self._next_id(), "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[msg["id"]] = fut
        await self.ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except Exception:
            self._pending.pop(msg["id"], None)
            raise

    async def reader(self):
        """Dispatch CDP traffic. Never await nested ``call`` here — that deadlocks."""
        async for raw in self.ws:
            data = json.loads(raw)
            if "id" in data and data["id"] in self._pending:
                fut = self._pending.pop(data["id"])
                if not fut.done():
                    if "error" in data:
                        fut.set_exception(RuntimeError(data["error"]))
                    else:
                        fut.set_result(data.get("result"))
                continue
            method = data.get("method")
            params = data.get("params") or {}
            if method == "Target.attachedToTarget":
                session_id = params.get("sessionId")
                info = params.get("targetInfo") or {}
                if session_id:
                    self._spawn_handle(
                        session_id, info, bool(params.get("waitingForDebugger"))
                    )
            elif method == "Target.targetCreated":
                info = params.get("targetInfo") or {}
                tid = info.get("targetId")
                if info.get("type") in ("page", "iframe") and tid and tid not in self._spoofed:
                    self._spawn_attach(tid)

    def _spawn_handle(self, session_id: str, info: dict, waiting: bool) -> None:
        task = asyncio.create_task(self._handle_target(session_id, info, waiting))
        task.add_done_callback(self._log_task_err)

    def _spawn_attach(self, target_id: str) -> None:
        task = asyncio.create_task(self._attach(target_id))
        task.add_done_callback(self._log_task_err)

    @staticmethod
    def _log_task_err(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            log.warning("background CDP task failed: %s: %s", type(exc).__name__, exc or "no message")

    async def _attach(self, target_id: str) -> None:
        try:
            await self.call(
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
            )
        except Exception as exc:
            log.debug("attach failed: %s", exc)

    async def _handle_target(self, session_id: str, info: dict, waiting: bool) -> None:
        """Spoof one attached target (page / iframe / worker) then ALWAYS resume it.

        With waitForDebuggerOnStart the target is frozen until
        ``Runtime.runIfWaitingForDebugger`` — so the spoof lands before any page
        script runs, and a failure here must never leave a tab hanging.
        """
        ttype = info.get("type")
        tid = info.get("targetId") or session_id
        try:
            if ttype in ("page", "iframe"):
                async with self._spoof_lock:
                    seen = tid in self._spoofed
                    self._spoofed.add(tid)
                if not seen:
                    await self._spoof_page(session_id)
            elif ttype in ("worker", "shared_worker", "service_worker"):
                await self.call(
                    "Runtime.evaluate",
                    {"expression": self.script},
                    session_id=session_id,
                    timeout=5.0,
                )
                log.info("WebGL spoof applied to %s %s", ttype, session_id[:8])
        except Exception as exc:
            if ttype in ("page", "iframe"):
                async with self._spoof_lock:
                    self._spoofed.discard(tid)
            log.warning("spoof %s failed: %s: %s", ttype, type(exc).__name__, exc or "no message")
        finally:
            if waiting:
                try:
                    await self.call(
                        "Runtime.runIfWaitingForDebugger", session_id=session_id, timeout=5.0
                    )
                except Exception as exc:
                    log.debug("resume failed: %s", exc)

    async def _spoof_page(self, session_id: str) -> None:
        await self.call("Page.enable", session_id=session_id, timeout=5.0)
        # New-document hook first: it covers every document the page will ever load
        # (including the very first one of a tab opened by a link — that tab has no
        # document yet, so an « immediate » run would block and the tab would stay blank).
        await self.call(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": self.script},
            session_id=session_id,
            timeout=5.0,
        )
        # Already-loaded document (existing tab): best effort, never fatal.
        try:
            await self.call(
                "Runtime.evaluate",
                {"expression": self.script},
                session_id=session_id,
                timeout=3.0,
            )
        except Exception as exc:
            log.debug("immediate spoof skipped: %s", exc)
        # Dedicated workers of this page (and its OOPIFs) — paused until spoofed.
        try:
            await self.call(
                "Target.setAutoAttach",
                {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True},
                session_id=session_id,
                timeout=5.0,
            )
        except Exception as exc:
            log.debug("worker auto-attach skipped: %s", exc)
        log.info("WebGL spoof applied to session %s", session_id[:8])

    async def bootstrap(self):
        await self.call("Target.setDiscoverTargets", {"discover": True})
        await self.call(
            "Target.setAutoAttach",
            {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True},
        )
        # Existing targets — fire-and-forget; autoAttach also covers new ones.
        result = await self.call("Target.getTargets")
        for info in (result or {}).get("targetInfos", []):
            if info.get("type") in ("page", "iframe") and info.get("targetId"):
                self._spawn_attach(info["targetId"])


async def run_once(port: int, vendor: str, renderer: str) -> None:
    script = load_script(vendor, renderer)
    ws_url = debugger_url(port)
    if ws_url is None:
        raise RuntimeError("CDP not ready")
    log.info("Connected spoof to %s", ws_url)
    log.info("Vendor=%s", vendor)
    log.info("Renderer=%s", renderer)
    async with websockets.connect(ws_url, max_size=8 * 1024 * 1024) as ws:
        client = CdpClient(ws, script)
        reader = asyncio.create_task(client.reader())
        try:
            await client.bootstrap()
            await reader
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader


async def run(port: int, vendor: str, renderer: str) -> None:
    log.info("Waiting for Chrome DevTools on :%s", port)
    while True:
        while debugger_url(port) is None:
            await asyncio.sleep(0.5)
        try:
            await run_once(port, vendor, renderer)
            log.warning("CDP websocket closed — reconnecting")
        except Exception as exc:
            log.warning(
                "CDP session ended (%s: %s) — reconnecting",
                type(exc).__name__,
                exc or "no message",
            )
        await asyncio.sleep(0.8)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s webgl-spoof %(levelname)s %(message)s",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=int(os.environ.get("BOT_CHROME_PORT", "9222")))
    p.add_argument(
        "--vendor",
        default=os.environ.get("UNMASKED_VENDOR_WEBGL", DEFAULT_VENDOR),
    )
    p.add_argument(
        "--renderer",
        default=os.environ.get("UNMASKED_RENDERER_WEBGL", DEFAULT_RENDERER),
    )
    args = p.parse_args()
    try:
        asyncio.run(run(args.port, args.vendor, args.renderer))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.error("%s: %s", type(exc).__name__, exc or "no message")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
