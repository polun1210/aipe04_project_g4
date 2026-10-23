from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends

from app.calculator import Calculator, get_calculator
from app.catalog_source import CatalogSource, get_catalog_source
from app.corrections import UnknownRowError, drug_corrections
from app.drug_mapping import map_confirmed_drug
from app.errors import ApiError
from app.schemas.api import ErrorResponse
from app.schemas.assessment import Assessment
from app.schemas.case import (
    MAX_AGE,
    MIN_AGE,
    AssessmentRequest,
    BasicProfileSnapshot,
    CaseProfile,
    ConfirmedDrug,
    SelectedDrug,
    age_band_for,
    age_on,
)
from app.schemas.common import ExclusiveSelection
from app.schemas.drug_label import DrugDraft, DrugDraftRow
from app.schemas.enums import ErrorCode
from app.auth import get_current_user_id
from app.store import Store, get_store

router = APIRouter(tags=["評估"])

_UNKNOWN_PRODUCT_MESSAGE = "部分保健食品資料已失效，請重新上傳後再評估"
_VALIDATION_MESSAGE = "送出的資料有欄位需要修正"


def _freeze_drugs(
    request: AssessmentRequest, catalog: CatalogSource, drafts: dict[UUID, DrugDraft]
) -> ExclusiveSelection[SelectedDrug]:
    """每個確認的藥名對照目錄：沒改名沿用草稿的對照，改過名重新對照；認不得的藥是 unresolved，不是錯誤。"""
    drug_items = catalog.load().drug_items
    selected = [
        map_confirmed_drug(d.name, _draft_row(drafts, d), drug_items, d.dose_mg, d.times_per_day)
        for d in request.drugs.selected
    ]
    return ExclusiveSelection[SelectedDrug](selected=selected, none_selected=request.drugs.none_selected)


def _drug_drafts(request: AssessmentRequest, store: Store, user_id: UUID) -> dict[UUID, DrugDraft]:
    """這次送出有引用的藥包草稿；找不到或不是自己的就略過。"""
    ids = dict.fromkeys(d.draft_id for d in request.drugs.selected if d.draft_id is not None)
    found = {i: store.get_drug_draft(user_id, i) for i in ids}
    return {i: draft for i, draft in found.items() if draft is not None}


def _draft_row(drafts: dict[UUID, DrugDraft], drug: ConfirmedDrug) -> DrugDraftRow | None:
    draft = drafts.get(drug.draft_id) if drug.draft_id else None
    return next((r for r in draft.rows if r.row_id == drug.row_id), None) if draft else None


@router.post(
    "/api/assessments",
    response_model=Assessment,
    summary="開始評估",
    description=(
        "PG-007 最後一罐保健食品確認後呼叫（接 PG-008 報告呈現頁）。送出確認後的藥名與已核對的產品編號，"
        "年齡、性別、慢性病由後端從帳號讀。後端凍結個案、對照藥名並同步計算，回傳評估結果；"
        "藥名有帶 `draft_id`／`row_id` 時，後端拿藥包草稿比對，存下修正紀錄（05c）。"
    ),
    responses={
        409: {"model": ErrorResponse, "description": "有 product_id 查不到，details 列出是哪幾個"},
        422: {
            "model": ErrorResponse,
            "description": "送出的資料不完整、row_id 不在藥包草稿裡，或帳號的年齡不在可評估範圍",
        },
    },
)
def create_assessment(
    request: AssessmentRequest,
    calculator: Calculator = Depends(get_calculator),
    catalog: CatalogSource = Depends(get_catalog_source),
    store: Store = Depends(get_store),
    user_id: UUID = Depends(get_current_user_id),
) -> Assessment:
    products = store.get_products(request.product_ids)
    found_ids = {p.product_id for p in products}
    missing = [pid for pid in dict.fromkeys(request.product_ids) if pid not in found_ids]
    if missing:
        details = [f"product_ids：{pid}" for pid in missing]
        raise ApiError(409, ErrorCode.PRODUCT_NOT_FOUND, _UNKNOWN_PRODUCT_MESSAGE, details)

    account = store.get_profile(user_id)
    created_at = datetime.now(UTC)
    age = age_on(account.birth_year, account.birth_month, created_at.date())
    if age < MIN_AGE:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, [f"評估當天須年滿 {MIN_AGE} 歲"])
    if age > MAX_AGE:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, ["出生年月不合理，請到設定頁確認"])

    case_id = uuid4()
    drafts = _drug_drafts(request, store, user_id)
    try:
        corrections = drug_corrections(drafts, request.drugs.selected, case_id, created_at)
    except UnknownRowError as e:
        details = [f"drugs：row_id {r} 不在藥包草稿裡" for r in e.row_ids]
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, details) from e

    case = CaseProfile(
        case_id=case_id,
        user_id=user_id,
        created_at=created_at,
        decision_data_version=_decision_data_version(),
        basic_profile=BasicProfileSnapshot(age=age, sex=account.sex, age_band=age_band_for(age)),
        conditions=account.conditions,
        drugs=_freeze_drugs(request, catalog, drafts),
        supplements=products,
    )
    assessment = calculator.assess(case)
    store.save_assessment(case, assessment)
    store.save_drug_corrections(user_id, corrections)
    return assessment


def _decision_data_version() -> str:
    """規則表／換算係數／DRIs 的 seed 版本戳。真資料表好了之後改成從資料表讀。"""
    return "seed-2026w40.1"
