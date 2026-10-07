"""FastAPI 進入點。啟動：uv run uvicorn app.main:app --reload"""

from fastapi import FastAPI

from app.errors import register_error_handlers
from app.routers import assessments, catalog, products


def create_app() -> FastAPI:
    app = FastAPI(title="補對了嗎？API")
    register_error_handlers(app)
    app.include_router(catalog.router)
    app.include_router(products.router)
    app.include_router(assessments.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
