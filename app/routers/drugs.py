from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.catalog_source import CatalogSource, get_catalog_source
from app.drug_mapping import find_candidates, map_drug_name
from app.errors import ApiError
from app.extractor import Extractor, get_extractor
from app.schemas.api import ErrorResponse
from app.schemas.drug_label import DrugDraft, DrugLookupResponse
from app.schemas.enums import ErrorCode, ImageKind
from app.store import TEST_USER_ID, Store, get_store
from app.uploads import ensure_any_accepted, extraction_errors_as_api_error, to_image_inputs

router = APIRouter(tags=["藥包"])

_MAX_CANDIDATES = 10


@router.post(
    "/api/drug-drafts",
    response_model=DrugDraft,
    status_code=201,
    summary="上傳藥包照片，取得辨識草稿",
    description=(
        "PG-004 藥圖片上傳頁按「下一步」時呼叫。同步等待辨識與藥名對照，回傳校對頁要預填的草稿。"
        "「還有其他藥包？」選「有」時前端再打一次，會產生新的草稿（後端不合併多份草稿）。"
    ),
    responses={
        422: {"model": ErrorResponse, "description": "沒有上傳照片、檔案不是圖片，或照片都沒通過品質檢查"},
        502: {"model": ErrorResponse, "description": "辨識服務逾時或失敗"},
    },
)
def create_drug_draft(
    images: list[UploadFile] = File(default=[], description="藥包照片，至少 1 張"),
    extractor: Extractor = Depends(get_extractor),
    store: Store = Depends(get_store),
) -> DrugDraft:
    inputs = to_image_inputs([(ImageKind.DRUG_PACKAGE, images)])
    with extraction_errors_as_api_error():
        quality = extractor.check_quality(inputs)
        ensure_any_accepted(quality)
        draft = extractor.extract_drugs(uuid4(), inputs, quality)
    store.save_drug_draft(TEST_USER_ID, draft)
    return draft


@router.get(
    "/api/drugs/lookup",
    response_model=DrugLookupResponse,
    summary="查藥名對照與候選藥名",
    description=(
        "PG-005 藥人工校對頁修改藥名時呼叫。`mapped` 是這個名字現在對照成什麼（與送出評估時一致），"
        "`candidates` 是名稱包含輸入字串的候選藥物，最多 10 筆。"
    ),
    responses={422: {"model": ErrorResponse, "description": "藥名是空的"}},
)
def lookup_drug(
    name: str = Query(description="使用者輸入的藥名"),
    catalog: CatalogSource = Depends(get_catalog_source),
) -> DrugLookupResponse:
    name = name.strip()
    if not name:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "送出的資料有欄位需要修正", ["name：請輸入藥名"])
    drug_items = catalog.load().drug_items
    return DrugLookupResponse(
        mapped=map_drug_name(name, drug_items),
        candidates=find_candidates(name, drug_items, _MAX_CANDIDATES),
    )
