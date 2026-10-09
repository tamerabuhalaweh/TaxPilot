"""Request correlation IDs: inbound X-Request-ID honoured, otherwise generated; echoed back."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    header = "X-Request-ID"

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get(self.header) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[self.header] = correlation_id
        return response
