from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.response import error_response


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        code: str = "APP_ERROR",
        message: str = "An application error occurred",
        detail: str | None = None,
        status_code: int = 400,
        data: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code
        self.data = data
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found", detail: str | None = None) -> None:
        super().__init__(code="NOT_FOUND", message=message, detail=detail, status_code=404)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized", detail: str | None = None) -> None:
        super().__init__(code="UNAUTHORIZED", message=message, detail=detail, status_code=401)


class ForbiddenException(AppException):
    def __init__(self, message: str = "Forbidden", detail: str | None = None) -> None:
        super().__init__(code="FORBIDDEN", message=message, detail=detail, status_code=403)


class BadRequestException(AppException):
    def __init__(self, message: str = "Bad request", detail: str | None = None) -> None:
        super().__init__(code="BAD_REQUEST", message=message, detail=detail, status_code=400)


class ConflictException(AppException):
    def __init__(self, message: str = "Conflict", detail: str | None = None) -> None:
        super().__init__(code="CONFLICT", message=message, detail=detail, status_code=409)


class ServiceUnavailableException(AppException):
    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        detail: str | None = None,
        data: dict | None = None,
    ) -> None:
        super().__init__(
            code="SERVICE_UNAVAILABLE",
            message=message,
            detail=detail,
            status_code=503,
            data=data,
        )


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI application."""

    @app.exception_handler(AppException)
    async def app_exception_handler(_request: Request, exc: AppException) -> error_response:  # type: ignore[misc]
        kwargs: dict = {
            "code": exc.code,
            "message": exc.message,
            "detail": exc.detail,
            "status_code": exc.status_code,
        }
        if exc.data:
            kwargs["data"] = exc.data
        return error_response(**kwargs)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> error_response:  # type: ignore[misc]
        return error_response(
            code=f"HTTP_{exc.status_code}",
            message=str(exc.detail) if exc.detail else "HTTP error",
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> error_response:  # type: ignore[misc]
        errors = exc.errors()
        detail_messages = []
        for err in errors:
            loc_parts = [str(x) for x in err.get("loc", []) if str(x) != "body"]
            field = loc_parts[-1] if loc_parts else ""
            msg = err.get("msg", "")
            detail_messages.append(f"{field}: {msg}" if field else msg)
        return error_response(
            code="VALIDATION_ERROR",
            message="Validation failed",
            detail="; ".join(detail_messages),
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(_request: Request, exc: Exception) -> error_response:  # type: ignore[misc]
        return error_response(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
            detail=str(exc) if _request.app.state.settings.DEBUG else None,  # type: ignore[attr-defined]
            status_code=500,
        )
