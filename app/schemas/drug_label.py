"""交接點 ④-藥：藥包辨識草稿。

藥包辨識只負責「藥包上寫了什麼」，再加上藥名對照的結果。一批可以有多張照片，一張可以有多個藥名。
複方藥對照到目錄中的一個複方品項，所以一列草稿只有一個 active_ingredient_code。
"""

from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.catalog import Code
from app.schemas.common import BoundingBox, StrictModel
from app.schemas.case import SelectedDrug
from app.schemas.enums import DrugClassCode, ScopeStatus
from app.schemas.label import ExtractionMeta, SourceImage, check_unique_rows


class DrugDraftRow(StrictModel):
    row_id: str  # 同一份草稿內唯一，例如 d01；校對與修正紀錄都靠它定位
    raw_name: str  # 藥包上印的原文（商品名、學名或中文名），之後不可修改
    generic_name_raw: str | None = None  # 藥包上另外印的學名原文；讀不到就 null
    source_image_id: str
    bbox: BoundingBox | None = None
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    # 藥名對照結果。送出評估時，使用者沒改藥名就沿用這裡（後端存的那份草稿，不信前端送來的）；
    # 改過名就重新對照。見 app/drug_mapping.py 的 map_confirmed_drug
    active_ingredient_code: Code | None = None
    scope_status: ScopeStatus

    @model_validator(mode="after")
    def _scope_iff_code(self) -> "DrugDraftRow":
        if (self.scope_status is ScopeStatus.IN_SCOPE) != (self.active_ingredient_code is not None):
            raise ValueError("scope_status = in_scope 若且唯若 active_ingredient_code 非 null")
        return self


class DrugDraft(StrictModel):
    """藥包照片上傳後，同步回傳的辨識草稿。"""

    draft_id: UUID
    source_images: list[SourceImage] = Field(min_length=1)
    rows: list[DrugDraftRow]  # 可以是空的（照片清楚，但沒讀到藥名）
    extraction_meta: ExtractionMeta

    @model_validator(mode="after")
    def _unique_rows(self) -> "DrugDraft":
        check_unique_rows([r.row_id for r in self.rows])
        return self


class DrugCandidate(StrictModel):
    active_ingredient_code: Code
    display_name_zh: str
    english_name: str
    matched_name: str  # 命中的那個名稱（可能是商品名），給前端顯示
    drug_class_codes: list[DrugClassCode]


class DrugLookupResponse(StrictModel):
    """校對頁修改藥名時，同時拿到「這個名字現在對照成什麼」和「候選藥名」。"""

    mapped: SelectedDrug  # 跟送出評估時的對照結果一模一樣（同一個 map_drug_name）
    candidates: list[DrugCandidate] = Field(max_length=10)
