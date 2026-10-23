"""交接點 ④-藥：藥包辨識草稿。

藥包辨識只負責「藥包上寫了什麼」，再加上藥名對照的結果。一批可以有多張照片，一張可以有多個藥名。
複方藥對照到目錄中的一個複方品項，所以一列草稿只有一個 active_ingredient_code。
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.catalog import Code
from app.schemas.common import BoundingBox, StrictModel
from app.schemas.case import SelectedDrug
from app.schemas.enums import CorrectionType, DrugClassCode, ScopeStatus
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


class DrugCorrection(StrictModel):
    """藥名校對的修正紀錄（05c），送出評估時後端比對藥包草稿與確認的藥名產生。藥包辨識準確率的來源。

    field_path 格式：rows.<row_id>.name（改名）／ rows.<row_id>（整列刪除）／ rows.new<n>（使用者新增）
    只比對有送出藥名的草稿；某一批的藥被全部刪掉時，前端沒送那份草稿的編號，後端無從得知，不會產生 removed。
    """

    case_id: UUID  # 哪一次評估送出的
    draft_id: UUID | None  # 使用者新增的藥為 null
    field_path: str
    correction_type: CorrectionType
    model_value: str | None  # 草稿原文；新增為 null
    corrected_value: str | None  # 使用者確認的藥名；刪除為 null
    # 辨識版本取自該份草稿；新增的藥不屬於任何草稿，三者都是 null
    ocr_version: str | None
    rule_layer_version: str | None
    synonym_table_version: str | None
    corrected_at: datetime

    @model_validator(mode="after")
    def _added_has_no_draft(self) -> "DrugCorrection":
        added = self.correction_type is CorrectionType.ADDED
        versions = (self.ocr_version, self.rule_layer_version, self.synonym_table_version)
        if added != (self.draft_id is None) or (added != all(v is None for v in versions)):
            raise ValueError("只有新增的藥沒有 draft_id 與辨識版本，其他一定要有")
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
