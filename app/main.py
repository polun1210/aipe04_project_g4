"""FastAPI 進入點。啟動：uv run uvicorn app.main:app --reload"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.errors import register_error_handlers
from app.routers import assessments, catalog, drugs, products, reports, supplements

_DESCRIPTION = """
- 所有網址都同步回傳：辨識、評估、產生報告都是等回應，不建工作編號。
- 失敗格式統一：一律回 `ErrorResponse`（`error.code`、`error.message`、選填的 `error.details`）。
- 還沒登入前，一律用測試帳號。
"""


def _use_binary_format_for_uploads(schema: dict[str, Any]) -> None:
    """list[UploadFile] 產生的 contentMediaType 欄位，Swagger UI 不會顯示成選檔按鈕；換成 format: binary。"""
    for body in schema.get("components", {}).get("schemas", {}).values():
        for prop in body.get("properties", {}).values():
            items = prop.get("items")
            if isinstance(items, dict) and items.get("contentMediaType") == "application/octet-stream":
                prop["items"] = {"type": "string", "format": "binary"}


def create_app() -> FastAPI:
    app = FastAPI(title="補對了嗎？API", description=_DESCRIPTION)
    register_error_handlers(app)
    app.include_router(catalog.router)
    app.include_router(drugs.router)
    app.include_router(products.router)
    app.include_router(supplements.router)
    app.include_router(assessments.router)
    app.include_router(reports.router)

    @app.get("/api/health", tags=["選單"], summary="確認服務有在跑")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title, version=app.version, description=app.description, routes=app.routes
            )
            _use_binary_format_for_uploads(schema)
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app


app = create_app()
