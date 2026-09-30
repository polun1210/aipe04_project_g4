"""交接點 ①：目錄資料（建表組 → 後端、前端選單）。

每個類別對應 data/catalogs/ 底下一個 CSV，一列 ＝ 一個模型實例。
範例見 docs/schemas/examples/catalog/。
"""

from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from app.schemas.common import PipeList, StrictModel
from app.schemas.enums import (
    ALLOWED_INGREDIENTS,
    AgeBand,
    ConditionCode,
    DrugClassCode,
    DrugClassRole,
    IngredientCategory,
    IngredientCode,
    MenuGroup,
    ReferenceType,
    Sex,
    ULScope,
    Unit,
)

Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]
"""小寫 snake_case 代碼，例如 atorvastatin、calcium_citrate。"""


class KnownCondition(StrictModel):
    """known_conditions.csv（5 列）"""

    condition_code: ConditionCode
    display_name_zh: str  # 勾選框上的白話文字
    backend_name: str
    sort_order: int


class DrugClass(StrictModel):
    """drug_classes.csv（16 列）"""

    drug_class_code: DrugClassCode
    display_name_zh: str
    plain_description_zh: str  # 一般民眾看得懂的說明
    role: DrugClassRole
    menu_group: MenuGroup  # 選單上放在哪一組瀏覽


class DrugItem(StrictModel):
    """drug_items.csv（約 44 列）。使用者實際勾選的是這一層。"""

    active_ingredient_code: Code
    display_name_zh: str
    english_name: str
    drug_class_codes: PipeList[DrugClassCode] = Field(min_length=1)  # 複方對應多個類別
    common_tradenames_tw: PipeList[str] = Field(min_length=1)
    related_conditions: PipeList[ConditionCode] = Field(default_factory=list)  # 只排序，不過濾
    requires_dose: bool = False  # 只有含鈣／含鎂制酸劑與軟便劑為 true


class DrugNutrientDose(StrictModel):
    """drug_nutrient_doses.csv：需要劑量的藥（制酸劑類）的劑量選項與元素量。"""

    active_ingredient_code: Code
    dose_option_mg: float = Field(gt=0)
    nutrient_code: IngredientCode
    elemental_mg_per_unit: float = Field(gt=0)
    source: str


class Ingredient(StrictModel):
    """ingredients.csv（16 列）：範圍內成分目錄，也是 HITL 成分名稱封閉選單的來源。"""

    code: IngredientCode
    category: IngredientCategory
    display_name_zh: str  # 校對介面與報告顯示的名稱，不參與計算
    standard_unit: Unit | None = None  # 目標營養素必填；允許成分只判有無，為 null
    accepted_units: PipeList[Unit] = Field(default_factory=list)  # HITL 改名稱後檢查單位用
    synonyms: PipeList[str] = Field(min_length=1)  # 名稱標準化（同義詞表）
    ul_scope: ULScope | None = None  # null ＝ 無 UL（鉀、B12）或允許成分

    @model_validator(mode="after")
    def _category_matches_code(self) -> "Ingredient":
        is_allowed = self.code in ALLOWED_INGREDIENTS
        if is_allowed != (self.category is IngredientCategory.ALLOWED_INGREDIENT):
            raise ValueError(f"{self.code} 的 category 與代碼不符")
        if not is_allowed and self.standard_unit is None:
            raise ValueError(f"目標營養素 {self.code} 必須有 standard_unit")
        return self


class OutOfScopeName(StrictModel):
    """out_of_scope_names.csv：已知範圍外清單。命中者 scope_status = out_of_scope。

    特別要收容易誤對映的名稱，例如「硬脂酸鎂」（賦形劑，不是鎂補充）。
    """

    name: str
    note: str | None = None


class DrisValue(StrictModel):
    """dris_values.csv：營養素 × 性別 × 年齡組 → 建議總攝取量與上限。"""

    nutrient_code: IngredientCode
    sex: Sex
    age_band: AgeBand
    reference_type: ReferenceType
    reference_value: float = Field(gt=0)
    ul_value: float | None = Field(default=None, gt=0)  # null ＝ DRIs 無上限
    unit: Unit


class CompoundRatio(StrictModel):
    """compound_ratios.csv：化合物的元素量比率（ADR-0004）。不得硬編碼在程式裡。"""

    compound_code: Code  # 例如 calcium_citrate
    nutrient_code: IngredientCode
    ratio: float = Field(gt=0, le=1)
    source: str


class ConversionFactor(StrictModel):
    """conversion_factors.csv：單位換算（IU → ug、IU → mg_ate、型態換算）。"""

    nutrient_code: IngredientCode
    from_unit: Unit
    to_unit: Unit
    factor: float = Field(gt=0)
    applies_to_form: str  # "all" 或 nutrient_form_code
    source: str


class CatalogResponse(StrictModel):
    """GET /api/catalog：前端選單一次取回。排序（相關疾病置頂）由前端依 related_conditions 做。"""

    known_conditions: list[KnownCondition]
    drug_classes: list[DrugClass]
    drug_items: list[DrugItem]
    drug_nutrient_doses: list[DrugNutrientDose]
    ingredients: list[Ingredient]
