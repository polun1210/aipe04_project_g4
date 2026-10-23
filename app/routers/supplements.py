from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.errors import ApiError
from app.extractor import Extractor, get_extractor
from app.schemas.api import ErrorResponse
from app.schemas.enums import ErrorCode, ImageKind
from app.schemas.label import ExtractionDraft
from app.auth import get_current_user_id
from app.store import Store, get_store
from app.uploads import ensure_any_accepted, extraction_errors_as_api_error, to_image_inputs

router = APIRouter(tags=["保健食品"])

MAX_CATEGORY_LENGTH = 30


def _clean_category(category: str | None) -> str | None:
    """去頭尾空白；空字串當作沒填；超過上限回 422。選項還沒定案，所以不限制內容。"""
    cleaned = (category or "").strip()
    if len(cleaned) > MAX_CATEGORY_LENGTH:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, "送出的資料有欄位需要修正", [f"category：最多 {MAX_CATEGORY_LENGTH} 個字"]
        )
    return cleaned or None


@router.post(
    "/api/supplement-drafts",
    response_model=ExtractionDraft,
    status_code=201,
    summary="上傳保健食品照片，取得辨識草稿",
    description=(
        "PG-006 保健食品圖片上傳頁按「下一步」時呼叫。成分表與營養標示兩個欄位合計至少 1 張，"
        "同步等待辨識。`category`（保健食品種類）只用來當產品的顯示名稱，不參與計算；"
        "辨識結果已經有產品名稱時以辨識的為準。"
    ),
    responses={
        422: {"model": ErrorResponse, "description": "沒有上傳照片、檔案不是圖片、種類太長，或照片都沒通過品質檢查"},
        502: {"model": ErrorResponse, "description": "辨識服務逾時或失敗"},
    },
)
def create_supplement_draft(
    ingredient_images: list[UploadFile] = File(default=[], description="成分表照片"),
    nutrition_images: list[UploadFile] = File(default=[], description="營養標示照片"),
    category: str | None = Form(default=None, description="保健食品種類（選填），例如「魚油」"),
    extractor: Extractor = Depends(get_extractor),
    store: Store = Depends(get_store),
    user_id: UUID = Depends(get_current_user_id),
) -> ExtractionDraft:
    category = _clean_category(category)
    inputs = to_image_inputs(
        [
            (ImageKind.SUPPLEMENT_INGREDIENTS, ingredient_images),
            (ImageKind.SUPPLEMENT_NUTRITION, nutrition_images),
        ]
    )
    with extraction_errors_as_api_error():
        quality = extractor.check_quality(inputs)
        ensure_any_accepted(quality)
        draft = extractor.extract_supplement(uuid4(), inputs, quality)
    if draft.product_name is None and category is not None:
        draft = draft.model_copy(update={"product_name": category})
    store.save_supplement_draft(user_id, draft)
    return draft
