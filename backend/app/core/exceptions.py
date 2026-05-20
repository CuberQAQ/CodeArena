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
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code
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


def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI application."""

    @app.exception_handler(AppException)
    async def app_exception_handler(_request: Request, exc: AppException) -> error_response:  # type: ignore[misc]
        return error_response(
            code=exc.code,
            message=exc.message,
            detail=exc.detail,
            status_code=exc.status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> error_response:  # type: ignore[misc]
        return error_response(
            code=f"HTTP_{exc.status_code}",
            message=str(exc.detail) if exc.detail else "HTTP error",
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> error_response:  # type: ignore[misc]
        errors = exc.errors()
        field_labels = {"username": "用户名", "email": "邮箱", "password": "密码", "confirmPassword": "确认密码"}
        detail_messages = []
        for err in errors:
            loc_parts = [str(x) for x in err.get("loc", []) if str(x) != "body"]
            field = field_labels.get(loc_parts[-1], loc_parts[-1]) if loc_parts else ""
            msg = err.get("msg", "")
            if "at least" in msg and "characters" in msg:
                import re
                m = re.search(r"at least (\d+) characters", msg)
                n = m.group(1) if m else "?"
                detail_messages.append(f"{field}至少需要{n}个字符" if field else f"至少需要{n}个字符")
            elif "uppercase" in msg:
                detail_messages.append(f"{field}必须包含至少一个大写字母" if field else "必须包含至少一个大写字母")
            elif "lowercase" in msg:
                detail_messages.append(f"{field}必须包含至少一个小写字母" if field else "必须包含至少一个小写字母")
            elif "digit" in msg:
                detail_messages.append(f"{field}必须包含至少一个数字" if field else "必须包含至少一个数字")
            elif "valid email" in msg:
                detail_messages.append("请输入有效的邮箱地址")
            elif "letters, digits, and underscores" in msg:
                detail_messages.append(f"{field}只能包含字母、数字和下划线" if field else "只能包含字母、数字和下划线")
            else:
                detail_messages.append(f"{field}: {msg}" if field else msg)
        return error_response(
            code="VALIDATION_ERROR",
            message="请求验证失败",
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
