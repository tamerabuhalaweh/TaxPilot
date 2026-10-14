"""Request correlation IDs: validated inbound value honoured, otherwise generated; echoed back.

Validation: 1–128 chars of [A-Za-z0-9_-]. Anything else is replaced with a fresh UUID
so oversized or hostile values can never flow into logs, headers, or error envelopes.
"""

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def coerce_correlation_id(raw: str | None) -> str:
    if raw and _SAFE_ID.match(raw):
        return raw
    return str(uuid.uuid4())


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    header = "X-Request-ID"

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = coerce_correlation_id(request.headers.get(self.header))
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[self.header] = correlation_id
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Enforce a request-body cap with and without Content-Length.

    A declared Content-Length above the cap is rejected before reading. Bodies
    arriving without (or with a lying) length are capped while streaming: the
    first byte past the limit aborts with 413.

    EP-04B intake uploads bypass this buffer: the upload route streams under
    its own per-route cap (upload_max_bytes) instead of the JSON body cap, so
    large quarantined files never sit buffered here. All other routes keep the
    default protection.
    """

    # POST bodies under this path suffix stream under route-owned caps.
    UPLOAD_BYPASS_SUFFIX = "/document-intakes"

    def __init__(self, app, max_bytes: int):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "POST" and request.url.path.endswith(self.UPLOAD_BYPASS_SUFFIX):
            return await call_next(request)
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    return _too_large(request)
            except ValueError:
                pass  # malformed length: fall through to the streaming cap below
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > self.max_bytes:
                return _too_large(request)
        # Repopulate Starlette's body cache so downstream handlers read normally.
        request._body = bytes(body)  # type: ignore[attr-defined]
        return await call_next(request)


def _too_large(request: Request):  # type: ignore[no-untyped-def]
    from starlette.responses import JSONResponse

    body = {"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body exceeds the allowed size."}}
    response = JSONResponse(status_code=413, content=body)
    correlation = getattr(request.state, "correlation_id", None)
    if correlation:
        response.headers[CorrelationIdMiddleware.header] = correlation
    return response
