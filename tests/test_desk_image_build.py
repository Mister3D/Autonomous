"""Desk image auto-build helpers (hash / need-build, no real docker build)."""

from __future__ import annotations

from pathlib import Path

from autonomous.services import desk_image_build as dib


def test_source_hash_stable(tmp_path: Path, monkeypatch):
    desk = tmp_path / "desktop"
    desk.mkdir()
    (desk / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (desk / "entrypoint.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(dib, "source_dir", lambda: desk)
    a = dib.source_hash()
    b = dib.source_hash()
    assert a == b
    assert len(a) == 16
    (desk / "entrypoint.sh").write_text("#!/bin/sh\necho changed\n", encoding="utf-8")
    assert dib.source_hash() != a


def test_needs_build_when_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(dib, "docker_ok", lambda: True)
    monkeypatch.setattr(dib, "image_present", lambda tag=None: False)
    monkeypatch.setattr(dib, "source_hash", lambda src=None: "abc")
    monkeypatch.setattr(dib, "image_tag", lambda home=None: "autonomous-desktop:latest")
    monkeypatch.setattr(dib, "_read_status", lambda home=None: {})
    assert dib.needs_build(tmp_path) is True


def test_needs_build_false_when_ready(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(dib, "docker_ok", lambda: True)
    monkeypatch.setattr(dib, "image_present", lambda tag=None: True)
    monkeypatch.setattr(dib, "source_hash", lambda src=None: "abc")
    monkeypatch.setattr(dib, "image_tag", lambda home=None: "autonomous-desktop:latest")
    monkeypatch.setattr(dib, "_read_status", lambda home=None: {"state": "ready", "hash": "abc"})
    assert dib.needs_build(tmp_path) is False


def test_needs_build_when_stale(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(dib, "docker_ok", lambda: True)
    monkeypatch.setattr(dib, "image_present", lambda tag=None: True)
    monkeypatch.setattr(dib, "source_hash", lambda src=None: "newhash")
    monkeypatch.setattr(dib, "image_tag", lambda home=None: "autonomous-desktop:latest")
    monkeypatch.setattr(dib, "_read_status", lambda home=None: {"state": "ready", "hash": "oldhash"})
    assert dib.needs_build(tmp_path) is True
