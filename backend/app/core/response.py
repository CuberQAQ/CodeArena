from typing import Any

from fastapi.responses import JSONResponse


def success_response(data: Any = None, message: str = "Success", status_code: int = 200) -> JSONResponse:
    """Return a unified success response."""
    return JSONResponse(
        status_code=status_code,
        content={"success": True, "data": data, "message": message},
    )


def error_response(
    code: str,
    message: str,
    detail: str | None = None,
    status_code: int = 400,
) -> JSONResponse:
    """Return a unified error response."""
    content: dict[str, Any] = {
        "success": False,
        "error": {"code": code, "message": message},
    }
    if detail is not None:
        content["detail"] = detail
    return JSONResponse(status_code=status_code, content=content)
