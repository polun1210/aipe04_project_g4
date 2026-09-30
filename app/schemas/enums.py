"""第一版所有封閉列舉。

原則：能列舉的一律列舉，不接受自由文字。
新增值 = 發 PR；刪除或改名 = 先在群組通知（會打壞別人的資料）。
"""

from enum import StrEnum

# ─── 使用者基本資料 ─────────────────────────────────────────


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class AgeBand(StrEnum):
    """DRIs 第八版的成人年齡分組，決定查哪一組 DRIs 值。"""

    Y19_30 = "19-30"
    Y31_50 = "31-50"
    Y51_70 = "51-70"
    Y71_PLUS = "71+"


# ─── 慢性病與用藥（v1-scope-checklist §1）───────────────────


class ConditionCode(StrEnum):
    """使用者勾選的 5 種慢性病。只用於藥物選單排序與涵蓋聲明，不觸發任何規則。"""

    HYPERTENSION = "hypertension"
    T2DM = "t2dm"
    DYSLIPIDEMIA = "dyslipidemia"
    CHRONIC_ARTHRITIS = "chronic_arthritis"
    CHRONIC_INSOMNIA = "chronic_insomnia"


class MenuGroup(StrEnum):
    """藥物選單的分組：5 種慢性病 ＋ 獨立的腸胃用藥分組。"""

    HYPERTENSION = "hypertension"
    T2DM = "t2dm"
    DYSLIPIDEMIA = "dyslipidemia"
    CHRONIC_ARTHRITIS = "chronic_arthritis"
    CHRONIC_INSOMNIA = "chronic_insomnia"
    GASTROINTESTINAL = "gastrointestinal"


class DrugClassCode(StrEnum):
    """16 個用藥類別。"""

    THIAZIDE_DIURETIC = "thiazide_diuretic"
    ACEI_ARB = "acei_arb"
    CCB = "ccb"
    BIGUANIDE = "biguanide"
    INSULIN = "insulin"
    SGLT2 = "sglt2"
    STATIN = "statin"
    EZETIMIBE = "ezetimibe"
    COX2_INHIBITOR = "cox2_inhibitor"
    ACETAMINOPHEN = "acetaminophen"
    GLUCOSAMINE_RX = "glucosamine_rx"
    BZD_ZDRUG = "bzd_zdrug"
    MELATONIN_RX = "melatonin_rx"
    PPI = "ppi"
    H2RA = "h2ra"
    ANTACID_LAXATIVE = "antacid_laxative"


class DrugClassRole(StrEnum):
    RULE_BEARING = "rule_bearing"  # 規則型：會觸發判定
    COVERAGE_ONLY = "coverage_only"  # 覆蓋型：不觸發規則，但使用者必須找得到自己的藥


# ─── 成分（v1-scope-checklist §2、§3）───────────────────────


class IngredientCode(StrEnum):
    """範圍內成分的標準代碼（standard_code）：13 項目標營養素 ＋ 3 項允許成分。

    範圍外成分（熱量、Q10、葉黃素…）沒有代碼，standard_code 為 null。
    """

    # 13 項目標營養素（做數值判定）
    CALCIUM = "calcium"
    MAGNESIUM = "magnesium"
    IRON = "iron"
    ZINC = "zinc"
    POTASSIUM = "potassium"
    VITAMIN_D = "vitamin_d"
    VITAMIN_E = "vitamin_e"
    VITAMIN_B12 = "vitamin_b12"
    FOLATE = "folate"
    NIACIN = "niacin"
    VITAMIN_C = "vitamin_c"
    VITAMIN_B6 = "vitamin_b6"
    SELENIUM = "selenium"
    # 3 項允許成分（只判有沒有，ADR-0007）
    RED_YEAST_RICE = "red_yeast_rice"
    GLUCOSAMINE = "glucosamine"
    OMEGA_3 = "omega_3"  # 魚油、EPA、DHA 都對映到這裡，用 nutrient_form_code 區分


ALLOWED_INGREDIENTS: frozenset[IngredientCode] = frozenset(
    {IngredientCode.RED_YEAST_RICE, IngredientCode.GLUCOSAMINE, IngredientCode.OMEGA_3}
)
TARGET_NUTRIENTS: frozenset[IngredientCode] = frozenset(IngredientCode) - ALLOWED_INGREDIENTS


class IngredientCategory(StrEnum):
    TARGET_NUTRIENT = "target_nutrient"
    ALLOWED_INGREDIENT = "allowed_ingredient"


class Unit(StrEnum):
    """單位一律用 ASCII 代碼。畫面上的「微克」「毫克」由模板轉換。

    不用 µg：µ 有 U+00B5 與 U+03BC 兩個碼位，NFKC 正規化後字串比對會失敗。
    """

    MG = "mg"
    UG = "ug"
    G = "g"
    KCAL = "kcal"
    IU = "iu"
    MG_ATE = "mg_ate"  # mg α-TE（維生素 E）
    MG_NE = "mg_ne"  # mg NE（菸鹼素）
    OTHER = "other"  # 只允許出現在範圍外成分（如 CFU、億）


# ─── 標示辨識 ───────────────────────────────────────────────


class QualityStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RejectReason(StrEnum):
    BLUR = "blur"
    GLARE = "glare"
    TRUNCATED = "truncated"
    SKEW = "skew"
    LOW_RESOLUTION = "low_resolution"
    UNSUPPORTED_LABEL = "unsupported_label"  # 不是台灣中文營養標示


class LabelSection(StrEnum):
    """此筆成分出自標示的哪個區塊。多圖合併時依此決定優先序（由上而下）。"""

    NUTRITION_TABLE = "nutrition_table"  # 營養標示方框
    PER_UNIT_NOTE = "per_unit_note"  # 每粒／每份含量說明小字
    INGREDIENT_LIST = "ingredient_list"  # 成分欄（允許成分通常在這裡）
    FRONT = "front"  # 正面行銷文案
    OTHER = "other"


class ScopeStatus(StrEnum):
    IN_SCOPE = "in_scope"  # 對映到目標營養素或允許成分，進入評估
    OUT_OF_SCOPE = "out_of_scope"  # 知道是什麼，但不評估（熱量、Q10）
    UNRESOLVED = "unresolved"  # 不知道是什麼；報告以警示語氣列出


class DoseUnit(StrEnum):
    CAPSULE = "capsule"
    TABLET = "tablet"
    SOFTGEL = "softgel"
    GUMMY = "gummy"
    SACHET = "sachet"
    SCOOP = "scoop"
    ML = "ml"
    DROP = "drop"
    G = "g"


class FrequencyType(StrEnum):
    DAILY = "daily"
    ALTERNATE_DAYS = "alternate_days"
    WEEKLY_N_TIMES = "weekly_n_times"
    CYCLIC_ON_OFF = "cyclic_on_off"
    AS_NEEDED = "as_needed"


class ElementalBasis(StrEnum):
    LABEL_STATED = "label_stated"  # 標示已載明元素量
    ESTIMATED = "estimated"  # 依化合物比率推估，報告必須寫「推估」（ADR-0004）
    UNKNOWN = "unknown"  # 無法判定，不納入計算
    NOT_APPLICABLE = "not_applicable"  # 非化合物類（維生素等）


class CorrectionType(StrEnum):
    MODIFIED = "modified"
    ADDED = "added"  # 使用者補上漏抓的列
    REMOVED = "removed"  # 使用者刪掉多抓的列（幻覺率的實地量測來源）


# ─── 規則表（rule-table.md）─────────────────────────────────


class ConditionType(StrEnum):
    DRUG_CLASS = "drug_class"
    DRUG_INGREDIENT = "drug_ingredient"


class InteractionType(StrEnum):
    ABSORPTION = "absorption"  # 吸收干擾
    PHARMACODYNAMIC = "pharmacodynamic"  # 藥效交互
    DRUG_AFFECTS_NUTRIENT = "drug_affects_nutrient"  # 藥物影響營養素（沒補也列出）


class Severity(StrEnum):
    """由高到低。聚合時取最高，永不降級（ADR-0009）。"""

    PRIORITY = "priority"  # 🔴
    ATTENTION = "attention"  # 🟡
    INFO = "info"  # 🔵


SEVERITY_RANK: dict[Severity, int] = {
    Severity.PRIORITY: 3,
    Severity.ATTENTION: 2,
    Severity.INFO: 1,
}


class AdviceCode(StrEnum):
    """建議行動的封閉列舉。不存在也不得新增停用、減量、改吃某產品（ADR-0001）。"""

    SEPARATE_TIMING = "separate_timing"
    INFORM_PROVIDER = "inform_provider"
    CONSULT_BEFORE_COMBINING = "consult_before_combining"


class RuleStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"  # 執行期只讀這個
    RETIRED = "retired"


class CitationSource(StrEnum):
    DRIS_TW = "dris_tw"
    NIH_ODS = "nih_ods"
    NCCIH = "nccih"
    OPENFDA_LABEL = "openfda_label"
    DAILYMED_LABEL = "dailymed_label"
    TFDA_LABEL = "tfda_label"
    PUBMED = "pubmed"
    SUPP_AI = "supp_ai"  # 只能輔助查漏，單獨不足以成立規則


class Jurisdiction(StrEnum):
    TW = "TW"
    US = "US"
    OTHER = "other"


class CandidateDirection(StrEnum):
    DECREASE = "decrease"
    INCREASE = "increase"
    INTERFERE = "interfere"


# ─── 評估與報告 ─────────────────────────────────────────────


class ReferenceType(StrEnum):
    """建議總攝取量（含飲食）的種類。"""

    RDA = "rda"
    AI = "ai"


class ULScope(StrEnum):
    SUPPLEMENT_ONLY = "supplement_only"  # 鎂、鐵：UL 原文即限定非食物來源
    TOTAL_INTAKE = "total_intake"  # 其餘：UL 含飲食，所以「未超過」不可講死


class ULPhrasing(StrEnum):
    """上限比對的封閉措辭，由 scope × exceeded 決定。文案在模板，不交給 LLM。"""

    EXCEEDED_SUPPLEMENT_ONLY = "exceeded_supplement_only"  # 已超過上限攝取量
    PERCENT_SUPPLEMENT_ONLY = "percent_supplement_only"  # 已達上限攝取量的 X%
    EXCEEDED_TOTAL_INTAKE = "exceeded_total_intake"  # 補充劑來源已超過上限攝取量
    PERCENT_TOTAL_INTAKE = "percent_total_intake"  # 補充劑來源已達上限的 X%（未含飲食）


class NarrationKind(StrEnum):
    """LLM 敘述對應到報告的哪一段。"""

    SUMMARY = "summary"
    DUPLICATE = "duplicate"
    NUTRIENT = "nutrient"
    INTERACTION = "interaction"


# ─── API ────────────────────────────────────────────────────


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    ALL_IMAGES_REJECTED = "all_images_rejected"
    PRODUCT_NOT_VERIFIED = "product_not_verified"
    JOB_FAILED = "job_failed"
