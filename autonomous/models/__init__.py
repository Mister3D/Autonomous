"""Marshmallow schemas for API validation / OpenAPI."""

from autonomous.models.schemas import (
    BotCreateSchema,
    BotPatchSchema,
    BotSchema,
    CapabilitySchema,
    DeskResetSchema,
    ErrorSchema,
    FilesQuerySchema,
    HealthSchema,
    JobSchema,
    LoginSchema,
    MessageCreateSchema,
    MessageSchema,
    SettingsSchema,
    TerminalExecSchema,
    TerminalLogSchema,
)

__all__ = [
    "BotCreateSchema",
    "BotPatchSchema",
    "BotSchema",
    "CapabilitySchema",
    "DeskResetSchema",
    "ErrorSchema",
    "FilesQuerySchema",
    "HealthSchema",
    "JobSchema",
    "LoginSchema",
    "MessageCreateSchema",
    "MessageSchema",
    "SettingsSchema",
    "TerminalExecSchema",
    "TerminalLogSchema",
]
