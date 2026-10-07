from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.calculator import Calculator, get_calculator
from app.catalog_source import CatalogSource, get_catalog_source
from app.errors import ApiError
from app.schemas.assessment import Assessment
from app.schemas.case import (
    AssessmentRequest,
    BasicProfileSnapshot,
    CaseProfile,
    SelectedDrug,
    age_band_for,
)
from app.schemas.common import ExclusiveSelection
from app.schemas.enums import ErrorCode
from app.store import TEST_USER_ID, Store, get_store

router = APIRouter()

_UNKNOWN_PRODUCT_MESSAGE = "有保健食品尚未核對完成，請回到前一步重新確認"
_VALIDATION_MESSAGE = "送出的資料有欄位需要修正"


def _freeze_drugs(request: AssessmentRequest, catalog: CatalogSource) -> ExclusiveSelection[SelectedDrug]:
    """把勾選的藥物補上目錄裡的名稱與類別；目錄沒有的代碼視為輸入錯誤。"""
    by_code = {item.active_ingredient_code: item for item in catalog.load().drug_items}
    unknown = [d.active_ingredient_code for d in request.drugs.selected if d.active_ingredient_code not in by_code]
    if unknown:
        details = [f"drugs.selected：不認得的藥物代碼 {code}" for code in unknown]
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, details)
    selected = [
        SelectedDrug(
            active_ingredient_code=d.active_ingredient_code,
            display_name_zh=by_code[d.active_ingredient_code].display_name_zh,
            drug_class_codes=by_code[d.active_ingredient_code].drug_class_codes,
            dose_mg=d.dose_mg,
            times_per_day=d.times_per_day,
        )
        for d in request.drugs.selected
    ]
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

    case = CaseProfile(
        case_id=uuid4(),
        user_id=TEST_USER_ID,
        created_at=datetime.now(UTC),
        decision_data_version=_decision_data_version(),
        basic_profile=BasicProfileSnapshot(
            age=request.basic_profile.age,
            sex=request.basic_profile.sex,
            age_band=age_band_for(request.basic_profile.age),
        ),
        conditions=request.conditions,
        drugs=_freeze_drugs(request, catalog),
        supplements=products,
    )
    assessment = calculator.assess(case)
    store.save_assessment(case, assessment)
    return assessment


def _decision_data_version() -> str:
    """規則表／換算係數／DRIs 的 seed 版本戳。真資料表好了之後改成從資料表讀。"""
    return "seed-2026w40.1"
