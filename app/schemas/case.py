"""交接點 ③：確認後的用藥（前端 → 後端）、帳號基本資料，以及凍結的評估個案。

年齡、性別、慢性病由後端從帳號讀（AccountProfile），前端只送藥名與產品編號。
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import ExclusiveSelection, FrozenModel, StrictModel
from app.schemas.enums import AgeBand, ConditionCode, DrugClassCode, ScopeStatus, Sex
from app.schemas.label import VerifiedProduct

MIN_AGE = 19  # DRIs 成人分組起點；第一版不支援未成年
MAX_AGE = 120


def age_band_for(age: int) -> AgeBand:
    if age <= 30:
        return AgeBand.Y19_30
    if age <= 50:
        return AgeBand.Y31_50
    if age <= 70:
        return AgeBand.Y51_70
    return AgeBand.Y71_PLUS


class ConfirmedDrug(StrictModel):
    """校對頁鎖定後的一筆藥。只送藥名文字，不送對照結果（後端重新對照）。"""

    draft_id: UUID | None = None  # 來自哪份藥包草稿；使用者自己新增的列為 null
    row_id: str | None = None  # 草稿原本的 row_id；使用者自己新增的列為 null
    name: str = Field(min_length=1)
    dose_mg: float | None = Field(default=None, gt=0)  # 制酸劑劑量從哪來還沒定案，先保留
    times_per_day: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _pairs(self) -> "ConfirmedDrug":
        if (self.draft_id is None) != (self.row_id is None):
            raise ValueError("draft_id 與 row_id 要一起填或一起不填")
        if (self.dose_mg is None) != (self.times_per_day is None):
            raise ValueError("dose_mg 與 times_per_day 要一起填或一起不填")
        return self


class AssessmentRequest(StrictModel):
    """POST /api/assessments。年齡、性別、慢性病不由前端送，後端從帳號讀。"""

    drugs: ExclusiveSelection[ConfirmedDrug]  # none_selected = 略過藥包辨識（「你沒有提供用藥資料」）
    product_ids: list[UUID] = Field(min_length=1)  # 至少一項已核對的保健食品


class AccountProfile(StrictModel):
    """評估時從帳號讀出的基本資料（註冊時填，設定頁可改）。"""

    birth_year: int = Field(ge=1900, le=2100)
    birth_month: int = Field(ge=1, le=12)
    sex: Sex
    conditions: ExclusiveSelection[ConditionCode]


def age_on(birth_year: int, birth_month: int, today: date) -> int:
    """評估當天的足歲。只有出生年月：當月視為已過生日。"""
    return today.year - birth_year - (1 if today.month < birth_month else 0)


# ═══ 凍結的評估個案（後端內部，存 case_profiles.profile JSONB）═══════


class BasicProfileSnapshot(FrozenModel):
    age: int = Field(ge=MIN_AGE, le=MAX_AGE)
    sex: Sex
    age_band: AgeBand  # 凍結當下算好，記錄當次查的是哪一組 DRIs

    @model_validator(mode="after")
    def _band_matches_age(self) -> "BasicProfileSnapshot":
        if self.age_band is not age_band_for(self.age):
            raise ValueError("age_band 與 age 不符")
        return self


class SelectedDrug(FrozenModel):
    """使用者確認的藥名 ＋ 後端凍結當下重新對照的結果。"""

    raw_name: str  # 使用者確認後的藥名文字
    scope_status: ScopeStatus
    active_ingredient_code: str | None = None  # 只有 in_scope 有值
    display_name_zh: str | None = None  # 只有 in_scope 有值（從目錄複製）
    drug_class_codes: list[DrugClassCode] = Field(default_factory=list)
    dose_mg: float | None = None
    times_per_day: int | None = None

    @model_validator(mode="after")
    def _scope_matches_fields(self) -> "SelectedDrug":
        has_all = bool(self.active_ingredient_code and self.display_name_zh and self.drug_class_codes)
        has_any = bool(self.active_ingredient_code or self.display_name_zh or self.drug_class_codes)
        if self.scope_status is ScopeStatus.IN_SCOPE:
            if not has_all:
                raise ValueError("in_scope 必須有代碼、中文名與至少一個用藥類別")
        elif has_any:
            raise ValueError("非 in_scope 的代碼、中文名、用藥類別都必須是空的")
        return self


class CaseProfile(FrozenModel):
    """評估個案：一次評估的不可變快照。不用外鍵指向可變的 users 表。"""

    case_id: UUID
    user_id: UUID
    created_at: datetime
    decision_data_version: str  # 規則表／換算係數／DRIs 的 seed 版本戳
    basic_profile: BasicProfileSnapshot
    conditions: ExclusiveSelection[ConditionCode]
    drugs: ExclusiveSelection[SelectedDrug]
    supplements: list[VerifiedProduct] = Field(min_length=1)
