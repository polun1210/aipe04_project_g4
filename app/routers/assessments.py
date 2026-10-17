from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.calculator import Calculator, get_calculator
from app.catalog_source import CatalogSource, get_catalog_source
from app.drug_mapping import map_drug_name
from app.errors import ApiError
from app.schemas.assessment import Assessment
from app.schemas.case import (
    MIN_AGE,
    AssessmentRequest,
    BasicProfileSnapshot,
    CaseProfile,
    SelectedDrug,
    age_band_for,
    age_on,
)
from app.schemas.common import ExclusiveSelection
from app.schemas.enums import ErrorCode
from app.store import TEST_USER_ID, Store, get_store

router = APIRouter()

_UNKNOWN_PRODUCT_MESSAGE = "有保健食品尚未核對完成，請回到前一步重新確認"
_VALIDATION_MESSAGE = "送出的資料有欄位需要修正"


def _freeze_drugs(request: AssessmentRequest, catalog: CatalogSource) -> ExclusiveSelection[SelectedDrug]:
    """每個確認的藥名重新對照目錄；認不得的藥是 unresolved，不是錯誤。"""
    drug_items = catalog.load().drug_items
    selected = [map_drug_name(d.name, drug_items, d.dose_mg, d.times_per_day) for d in request.drugs.selected]
    return ExclusiveSelection[SelectedDrug](selected=selected, none_selected=request.drugs.none_selected)


@router.post("/api/assessments", response_model=Assessment)
def create_assessment(
    request: AssessmentRequest,
    calculator: Calculator = Depends(get_calculator),
    catalog: CatalogSource = Depends(get_catalog_source),
    store: Store = Depends(get_store),
) -> Assessment:
    products = store.get_products(request.product_ids)
    if len(products) != len(set(request.product_ids)):
        raise ApiError(409, ErrorCode.PRODUCT_NOT_VERIFIED, _UNKNOWN_PRODUCT_MESSAGE)

    account = store.get_profile(TEST_USER_ID)
    created_at = datetime.now(UTC)
    age = age_on(account.birth_year, account.birth_month, created_at.date())
    if age < MIN_AGE:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, [f"評估當天須年滿 {MIN_AGE} 歲"])

    case = CaseProfile(
        case_id=uuid4(),
        user_id=TEST_USER_ID,
        created_at=created_at,
        decision_data_version=_decision_data_version(),
        basic_profile=BasicProfileSnapshot(age=age, sex=account.sex, age_band=age_band_for(age)),
        conditions=account.conditions,
        drugs=_freeze_drugs(request, catalog),
        supplements=products,
    )
    assessment = calculator.assess(case)
    store.save_assessment(case, assessment)
    return assessment


def _decision_data_version() -> str:
    """規則表／換算係數／DRIs 的 seed 版本戳。真資料表好了之後改成從資料表讀。"""
    return "seed-2026w40.1"
