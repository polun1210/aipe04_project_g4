"""交接點 ③：基本資料／疾病／用藥（前端 → 後端），以及凍結的評估個案。

③ 的子模型與評估個案共用，同一套驗證只寫一次。
表單若以一般 form POST 送出，後端也是組成 AssessmentRequest 再驗證。
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.catalog import Code
from app.schemas.common import ExclusiveSelection, FrozenModel, StrictModel
from app.schemas.enums import AgeBand, ConditionCode, DrugClassCode, Sex
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


class BasicProfile(StrictModel):
    """年齡與性別必填：決定查哪一組 DRIs 值。第一版只收這兩項個人資料。"""

    age: int = Field(ge=MIN_AGE, le=MAX_AGE)
    sex: Sex


class DrugChoice(StrictModel):
    """使用者勾選的一個有效成分。劑量只有制酸劑類（requires_dose = true）會填。"""

    active_ingredient_code: Code
    dose_mg: float | None = Field(default=None, gt=0)
    times_per_day: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _dose_pair(self) -> "DrugChoice":
        if (self.dose_mg is None) != (self.times_per_day is None):
            raise ValueError("dose_mg 與 times_per_day 要一起填或一起不填")
        return self


class AssessmentRequest(StrictModel):
    """POST /api/assessments：產品都核對完之後，送出建立一次評估。"""

    basic_profile: BasicProfile
    conditions: ExclusiveSelection[ConditionCode]
    drugs: ExclusiveSelection[DrugChoice]
    product_ids: list[UUID] = Field(min_length=1)  # 至少一項已核對的保健食品


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
    """DrugChoice ＋ 凍結當下從目錄複製的名稱與類別。"""

    active_ingredient_code: str
    display_name_zh: str
    drug_class_codes: list[DrugClassCode] = Field(min_length=1)
    dose_mg: float | None = None
    times_per_day: int | None = None


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
