"""Schedule prompts checked against the real model.

The default suite stays offline. The case below calls Pi only when
``AUTONOMOUS_LLM_TESTS=1``. ``date`` is answered on the host (no desk)
because the serve process is started with ``AUTONOMOUS_LLM_TEST_CLOCK=1``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autonomous import auth as auth_mod
from autonomous.db import migrate
from autonomous.paths import ensure_home
from autonomous.services import bots as bots_svc
from autonomous.services import settings as settings_svc
from autonomous.services import terminal as terminal_svc
from autonomous.services.cronutil import next_run_after

FOCUS_PROMPT = "Pendants 1h, rapelle moi toutes les 5 min de me focus !"


def focus_hour_problem(schedules: list[dict], anchor: datetime) -> str | None:
    """None when the crons are one hour of 5-minute reminders, then stop.

    The first slot may be the next 5-minute mark (up to 12 minutes after
    ``anchor``). A burst that keeps going, or a single reminder, fails.
    """
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    else:
        anchor = anchor.astimezone(timezone.utc)
    horizon = anchor + timedelta(hours=3)
    fires: list[datetime] = []
    for sched in schedules:
        if sched.get("enabled") is False:
            continue
        cron = sched.get("cron_utc") or sched.get("cron") or ""
        cursor = anchor - timedelta(seconds=1)
        for _ in range(80):
            try:
                nxt = next_run_after(cron, cursor)
            except ValueError:
                break
            if nxt > horizon:
                break
            if nxt >= anchor:
                fires.append(nxt)
            cursor = nxt
    fires = sorted(set(fires))
    if len(fires) < 11:
        return (
            f"{len(fires)} déclenchement(s) sur 3 h — "
            "attendu : toutes les 5 min pendant environ 1 h"
        )
    run = [fires[0]]
    for moment in fires[1:]:
        if moment - run[-1] == timedelta(minutes=5):
            run.append(moment)
        else:
            break
    span = run[-1] - run[0]
    if span < timedelta(minutes=50) or span > timedelta(minutes=65):
        return f"la série dure {span}, pas environ 1 h ({len(run)} créneaux)"
    if run[0] - anchor > timedelta(minutes=12):
        return f"le premier créneau est trop tard : {run[0].isoformat()}"
    later = run[-1] + timedelta(hours=6)
    extras: list[datetime] = []
    for sched in schedules:
        if sched.get("enabled") is False:
            continue
        cron = sched.get("cron_utc") or sched.get("cron") or ""
        cursor = run[-1]
        for _ in range(20):
            try:
                nxt = next_run_after(cron, cursor)
            except ValueError:
                break
            if nxt > later:
                break
            if nxt > run[-1] + timedelta(minutes=6):
                extras.append(nxt)
            cursor = nxt
    if extras:
        return f"la série continue après l'heure : {extras[0].isoformat()}"
    return None


def test_focus_hour_accepts_a_bounded_five_minute_series():
    anchor = datetime(2026, 11, 1, 12, 48, tzinfo=timezone.utc)
    schedules = [
        {"enabled": True, "cron_utc": "50,55 12 1 11 *"},
        {"enabled": True, "cron_utc": "0-45/5 13 1 11 *"},
    ]
    assert focus_hour_problem(schedules, anchor) is None


def test_focus_hour_rejects_a_single_reminder_and_an_endless_one():
    anchor = datetime(2026, 11, 1, 12, 48, tzinfo=timezone.utc)
    one = focus_hour_problem(
        [{"enabled": True, "cron_utc": "50 12 1 11 *"}],
        anchor,
    )
    assert one
    endless = focus_hour_problem(
        [{"enabled": True, "cron_utc": "*/5 * * * *"}],
        anchor,
    )
    assert endless


def test_llm_test_clock_runs_date_without_a_desk(home, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_LLM_TEST_CLOCK", "1")
    settings_svc.set_many({"timezone": "Europe/Paris"}, home=home)
    bots_svc.create_bot("clockbot", home=home)
    entry = terminal_svc.exec_command("clockbot", "date '+%H:%M'", home=home)
    assert entry["exit_code"] == 0
    assert len(entry["output"].strip().splitlines()[0]) == 5


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(method: str, url: str, token: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.status, json.load(res)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        return exc.code, parsed


@pytest.mark.llm
@pytest.mark.skipif(
    os.environ.get("AUTONOMOUS_LLM_TESTS") != "1",
    reason="appel réel au modèle : AUTONOMOUS_LLM_TESTS=1",
)
def test_focus_prompt_schedules_one_hour_every_five_minutes(tmp_path):
    home = ensure_home(tmp_path / "data")
    migrate(home)
    settings_svc.ensure_defaults(home)
    settings_svc.set_many(
        {"timezone": "Europe/Paris", "agent_backend": "pi"},
        home=home,
    )
    token = auth_mod.write_token(home, "llm-test-token")
    port = _free_port()
    env = os.environ.copy()
    env["AUTONOMOUS_HOME"] = str(home)
    env["AUTONOMOUS_LLM_TEST_CLOCK"] = "1"
    env.pop("WERKZEUG_RUN_MAIN", None)
    log_path = Path(tmp_path / "serve.log")
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            "autonomous",
            "serve",
            "--home",
            str(home),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as res:
                    if res.status == 200:
                        break
            except OSError:
                time.sleep(0.3)
        else:
            raise AssertionError(log_path.read_text(encoding="utf-8")[-2000:])

        model = os.environ.get("AUTONOMOUS_LLM_MODEL") or ""
        body = {"name": "Focus", "slug": "focus"}
        if model:
            body["model"] = model
        status, created = _request("POST", base + "/bots", token, body)
        assert status == 201, created
        sent_at = datetime.now(timezone.utc)
        status, msg = _request(
            "POST",
            base + "/bots/focus/messages",
            token,
            {"content": FOCUS_PROMPT},
        )
        assert status == 201, msg

        schedules: list[dict] = []
        stable = 0
        deadline = time.time() + 180
        while time.time() < deadline:
            status, bot = _request("GET", base + "/bots/focus", token)
            assert status == 200, bot
            status, schedules = _request("GET", base + "/bots/focus/schedules", token)
            assert status == 200, schedules
            if bot.get("status") == "idle" and schedules:
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
            time.sleep(2)
        else:
            _status, messages = _request(
                "GET", base + "/bots/focus/messages?limit=200", token
            )
            text = "\n".join(
                f"{m.get('role')}: {(m.get('content') or '')[:400]}"
                for m in (messages if isinstance(messages, list) else [])
            )
            raise AssertionError(
                "le modèle n'a pas fini une série\n"
                + json.dumps(schedules, ensure_ascii=False)[:2000]
                + "\n"
                + text[-2000:]
                + "\n"
                + log_path.read_text(encoding="utf-8")[-1500:]
            )

        problem = focus_hour_problem(schedules, sent_at)
        if problem:
            raise AssertionError(
                problem + "\n" + json.dumps(schedules, ensure_ascii=False)[:2000]
            )
    finally:
        log_file.close()
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, 15)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, 9)
                proc.wait(timeout=5)
