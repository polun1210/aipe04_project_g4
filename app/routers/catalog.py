from fastapi import APIRouter, Depends

from app.catalog_source import CatalogSource, get_catalog_source
from app.schemas.catalog import CatalogResponse

router = APIRouter()


@router.get("/api/catalog", response_model=CatalogResponse)
def get_catalog(source: CatalogSource = Depends(get_catalog_source)) -> CatalogResponse:
    return source.load()
