"""Job status API."""

from __future__ import annotations

from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from autonomous.models.schemas import JobSchema
from autonomous.services import jobs as jobs_svc
from autonomous.services.errors import AutonomousError

blp = Blueprint("jobs", __name__, url_prefix="/jobs", description="Jobs")


@blp.route("/<string:job_id>")
class JobDetail(MethodView):
    @blp.response(200, JobSchema)
    def get(self, job_id):
        """Get async job status."""
        try:
            return jobs_svc.get_job(job_id, home=g.home)
        except AutonomousError as exc:
            abort(exc.http_status, message=exc.message)
