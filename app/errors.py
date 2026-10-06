"""統一錯誤格式：所有失敗都回 ErrorResponse（docs/schemas/examples/api_error.json）。"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.api import ErrorBody, ErrorResponse
from app.schemas.enums import ErrorCode

_VALIDATION_MESSAGE = "送出的資料有欄位需要修正"
_HTTP_STATUS_TO_ERROR = {
    401: (ErrorCode.UNAUTHORIZED, "請先登入"),
    404: (ErrorCode.NOT_FOUND, "找不到要求的資料"),
    405: (ErrorCode.NOT_FOUND, "找不到要求的資料"),
}
_INTERNAL_MESSAGE = "系統發生問題，請稍後再試"
_VALUE_ERROR_PREFIX = "Value error, "  # pydantic 對自訂驗證器訊息加的英文前綴
_REQUEST_PART_NAMES = {"body", "query", "path", "header", "cookie"}


def _error_response(status_code: int, code: ErrorCode, message: str, details: list[str] | None = None):
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json", exclude_none=True))


def _describe(error: dict) -> str:
    """「欄位：訊息」。只用欄位路徑與驗證訊息，不回傳使用者送來的值。"""
    path = [str(p) for p in error["loc"] if p not in _REQUEST_PART_NAMES]
    message = error["msg"].removeprefix(_VALUE_ERROR_PREFIX)
    return f"{'.'.join(path)}：{message}" if path else message


async def _handle_validation_error(_: Request, exc: RequestValidationError):
    return _error_response(
        422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, [_describe(e) for e in exc.errors()]
    )


async def _handle_http_exception(_: Request, exc: StarletteHTTPException):
    code, message = _HTTP_STATUS_TO_ERROR.get(exc.status_code, (ErrorCode.INTERNAL_ERROR, _INTERNAL_MESSAGE))
    return _error_response(exc.status_code, code, message)


async def _handle_unexpected_error(_: Request, __: Exception):
    return _error_response(500, ErrorCode.INTERNAL_ERROR, _INTERNAL_MESSAGE)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
