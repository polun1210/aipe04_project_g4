"""FastAPI 進入點。啟動：uv run uvicorn app.main:app --reload"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="補對了嗎？API")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
