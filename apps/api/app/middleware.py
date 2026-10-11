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
