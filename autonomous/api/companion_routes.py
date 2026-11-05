"""Companion binary: build status, rebuild trigger and download."""

from __future__ import annotations

from flask import g, send_file
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from autonomous.services import companion_build as build_svc

blp = Blueprint(
    "companion_build", __name__, url_prefix="/companion",
    description="Companion binary build & download",
)


@blp.route("/build")
class CompanionBuild(MethodView):
    def get(self):
        """Build status, version, platforms and download URLs."""
        st = build_svc.status(g.home)
        for a in st["artifacts"]:
            a["url"] = f"/api/v1/companion/download/{a['target']}"
        return st

    def post(self):
        """Start a rebuild in the background (no-op if one is running)."""
        started = build_svc.start_background(g.home, force=True)
        st = build_svc.status(g.home)
        st["started"] = started
        return st


@blp.route("/download/<string:target>")
class CompanionDownload(MethodView):
    def get(self, target: str):
        """Download the companion binary for one Rust target triple."""
        path = build_svc.artifact_path(target, g.home)
        if path is None:
            abort(404, message="No companion build for this target")
        version = build_svc.crate_version() or "dev"
        stem = build_svc.BIN_NAME
        suffix = ".exe" if path.suffix == ".exe" else ""
        name = f"{stem}-{version}-{target}{suffix}"
        return send_file(path, as_attachment=True, download_name=name,
                         mimetype="application/octet-stream")
