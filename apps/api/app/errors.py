"""Error envelope: {error:{code,message,details,request_id}}. Public messages carry no internals."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


_STATUS_BY_CODE = {
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "OWNER_PROTECTED": 403,
    "NOT_FOUND": 404,
    "STATE_CONFLICT": 409,
    "APPROVAL_BLOCKED": 409,
    "VALIDATION_ERROR": 422,
    "RATE_LIMITED": 429,
    "PAYLOAD_TOO_LARGE": 413,  # per-route streaming caps (intake uploads)
    "STORAGE_UNAVAILABLE": 503,  # quarantine not approved for this environment
    "INTERNAL_ERROR": 500,  # default fallback, listed explicitly so the map stays total
    # Jurisdiction placeholders (contracts approved; enforcement lands with JUR-01/02)
    "JURISDICTION_NOT_SUPPORTED": 422,
    "TAX_CONTEXT_REQUIRED": 409,
    "TAX_PROFILE_UNVERIFIED": 422,
    "PACK_NOT_APPROVED": 409,
    "CROSS_ENTITY_SCOPE_CONFLICT": 409,
    "SOURCE_NOT_RELEASED": 409,  # REC-DATA-01: default-deny until release evidence exists
    "SOURCE_HEADERS_UNAVAILABLE": 409,  # REC-DATA-02: no trusted source-header attestation
    "MAPPING_APPROVAL_NOT_ENABLED": 409,  # REC-DATA-02: mapping approval default-deny
}


class AppError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def error_response(
    request: Request, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    status = _STATUS_BY_CODE.get(code, 500)
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details,
            request_id=getattr(request.state, "correlation_id", None),
        )
    )
    return JSONResponse(status_code=status, content=envelope.model_dump(exclude_none=True))


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(request, exc.code, exc.message, exc.details)


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:  # never leak internals
    return error_response(request, "INTERNAL_ERROR", "An unexpected error occurred.", None)
