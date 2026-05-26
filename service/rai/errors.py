"""Domain error hierarchy. Handlers raise these without importing FastAPI;
a single exception handler in main.py renders them as {"error": code, "message": ...}.
"""
from __future__ import annotations


class RaiError(Exception):
    """Base for all domain errors."""

    code: str = "internal"
    http_status: int = 500

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)
        self.message = message or self.code


class UnknownTenantError(RaiError):
    code = "unknown_tenant"
    http_status = 404


class UnknownSenderError(RaiError):
    code = "unknown_sender"
    http_status = 404


class UnknownOperationError(RaiError):
    code = "unknown_operation"
    http_status = 404


class UnauthorizedError(RaiError):
    code = "unauthorized"
    http_status = 403


class InvalidArgsError(RaiError):
    code = "invalid_args"
    http_status = 422


class NotImplementedOpError(RaiError):
    code = "not_implemented"
    http_status = 501
