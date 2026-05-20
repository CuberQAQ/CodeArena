import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.redis import RedisUnavailableError, close_redis_pool, init_redis_pool
from app.core.task_scheduler import scheduler as submission_scheduler
from app.middleware import LoggingMiddleware, RateLimitMiddleware, setup_cors

logger = logging.getLogger("code_arena")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown logic."""
    # Startup
    logger.info("Starting %s (debug=%s)", settings.APP_NAME, settings.DEBUG)

    # Auto-run database migrations on startup
    import subprocess
    import sys

    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "PYTHONPATH": "/app"},
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("Database migrations applied successfully")
        else:
            logger.warning("Database migration warning: %s", result.stderr[:200])
    except Exception as e:
        logger.warning("Database migration skipped: %s", e)

    # Start background submission tracking scheduler
    submission_scheduler.start(app)

    # Initialize Redis connection pool
    try:
        await init_redis_pool()
    except Exception as e:
        logger.error("Failed to initialize Redis: %s", e)

    yield
    # Shutdown
    await close_redis_pool()
    await submission_scheduler.stop()
    logger.info("Shutting down %s", settings.APP_NAME)
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="Competitive Programming Gamification Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

# Store settings and logger on app state for middleware access
app.state.settings = settings
app.state.logger = logger

# Register middleware (order matters: last added = first executed)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    max_requests=settings.RATE_LIMIT_PER_MINUTE,
    window_seconds=60,
)
setup_cors(app)

# Register global exception handlers
register_exception_handlers(app)


# Handle Redis unavailability as 503
@app.exception_handler(RedisUnavailableError)
async def redis_unavailable_handler(_request, exc):
    from app.core.response import error_response

    return error_response(
        code="SERVICE_UNAVAILABLE",
        message="Match service temporarily unavailable. Please try again.",
        detail=str(exc),
        status_code=503,
    )

# Mount API routes
app.include_router(api_router, prefix="/api/v1")
