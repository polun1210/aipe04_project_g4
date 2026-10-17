from fastapi import APIRouter, Depends

from app.catalog_source import CatalogSource, get_catalog_source
from app.schemas.catalog import CatalogResponse

router = APIRouter(tags=["選單"])


@router.get(
    "/api/catalog",
    response_model=CatalogResponse,
    summary="取得所有選單資料",
    description="PG-003 註冊頁、PG-009 用藥校對頁載入時呼叫：慢性病、用藥類別、藥物品項、營養素與成分目錄。",
)
def get_catalog(source: CatalogSource = Depends(get_catalog_source)) -> CatalogResponse:
    return source.load()
