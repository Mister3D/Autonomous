"""Domain errors."""

from __future__ import annotations


class AutonomousError(Exception):
    code = "error"
    http_status = 400

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code
        self.message = message


class NotFound(AutonomousError):
    code = "not_found"
    http_status = 404


class Conflict(AutonomousError):
    code = "conflict"
    http_status = 409


class Forbidden(AutonomousError):
    code = "forbidden"
    http_status = 403


class ValidationError(AutonomousError):
    code = "validation"
    http_status = 400
