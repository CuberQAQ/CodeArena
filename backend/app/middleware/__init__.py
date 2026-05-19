import time

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.config import settings


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs request method, path, status code, and duration."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        # Use the app's logger if available, otherwise print
        message = (
            f"{request.method} {request.url.path} "
            f"-> {response.status_code} ({duration_ms:.1f}ms)"
        )
        if hasattr(request.app.state, "logger") and request.app.state.logger:
            request.app.state.logger.info(message)
        else:
            print(message)

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiting middleware.

    Tracks request counts per client IP within a sliding window.
    Suitable for single-process deployments; for multi-process
    deployments, replace with a Redis-backed implementation.
    """

    def __init__(self, app: FastAPI, max_requests: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # {client_ip: [(timestamp, ...), ...]}
        self._requests: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # Clean up old entries and add current request
        if client_ip not in self._requests:
            self._requests[client_ip] = []

        # Remove timestamps outside the window
        self._requests[client_ip] = [
            ts for ts in self._requests[client_ip] if now - ts < self.window_seconds
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(
                content='{"success":false,"error":{"code":"RATE_LIMITED","message":"Too many requests"},"detail":null}',
                status_code=429,
                media_type="application/json",
            )

        self._requests[client_ip].append(now)
        response = await call_next(request)
        return response


def setup_cors(app: FastAPI) -> None:
    """Configure CORS middleware on the FastAPI application."""
    from starlette.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
