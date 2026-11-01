import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends

from app.calculator import Calculator, get_calculator, with_label_names
from app.corrections import UnknownRowError, label_corrections
from app.errors import ApiError
from app.schemas.api import ErrorResponse, ProductCreated
from app.schemas.enums import ErrorCode
from app.schemas.label import ExtractionDraft, VerificationSubmission
from app.auth import get_current_user_id
from app.store import Store, get_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["保健食品"])


@router.post(
    "/api/products",
    response_model=ProductCreated,
    status_code=201,
    summary="送出核對完成的保健食品",
    description=(
        "PG-007 保健食品人工校對頁全部鎖定、按「下一步」時呼叫。後端重算攝取量與營養素量"
        "（前端送來的計算欄位一律不採信），存成一罐已核對的產品，回傳 product_id 供送出評估時使用。"
        "帶 `draft_product_id` 時，後端拿那份辨識草稿比對，存下修正紀錄（給辨識準確率統計用）。"
    ),
    responses={
        422: {"model": ErrorResponse, "description": "送出的欄位不完整或格式不對，或 row_id 不在辨識草稿裡"}
    },
)
def create_product(
    submission: VerificationSubmission,
    calculator: Calculator = Depends(get_calculator),
    store: Store = Depends(get_store),
    user_id: UUID = Depends(get_current_user_id),
) -> ProductCreated:
    product_id, verified_at = uuid4(), datetime.now(UTC)
    draft = _find_draft(store, user_id, submission)
    if draft is not None:
        _save_corrections(store, user_id, draft, submission, product_id, verified_at)
    product = with_label_names(calculator.verify_product(product_id, submission, verified_at), draft)
    store.save_product(user_id, product)
    return ProductCreated(product_id=product.product_id)


def _find_draft(store: Store, user_id: UUID, submission: VerificationSubmission) -> ExtractionDraft | None:
    if submission.draft_product_id is None:
        return None
    draft = store.get_supplement_draft(user_id, submission.draft_product_id)
    if draft is None:
        # 草稿找不到（例如伺服器重啟過）不擋使用者送出：不產生修正紀錄，成分也拿不到標示原文
        logger.warning("找不到辨識草稿 %s，這罐不產生修正紀錄", submission.draft_product_id)
    return draft


def _save_corrections(
    store: Store, user_id: UUID, draft: ExtractionDraft, submission: VerificationSubmission, product_id: UUID, at: datetime
) -> None:
    try:
        corrections = label_corrections(draft, submission, product_id, at)
    except UnknownRowError as e:
        details = [f"nutrients：row_id {r} 不在辨識草稿裡" for r in e.row_ids]
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "送出的資料有欄位需要修正", details) from e
    store.save_label_corrections(user_id, corrections)
