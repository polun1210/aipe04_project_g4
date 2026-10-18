"""規則層：把 VLM 讀出的 LabelReading 整理成辨識草稿的欄位（E 工單 #22）。

只做「標示上寫了什麼」的整理，不做換算與推估（那些屬於後端）。規則照 spec「規則層（硬性要求）」：
- 標示原文照實保留；%DV 不得填進每份含量；範圍內成分的單位不得為 other
- 每一份量是劑型單位數，不是重量；劑型無法判定就留空
- 任何不確定的值：留空並標為需要使用者確認，不猜
名稱標準化照 spec「名稱標準化」：統一全形半形、去括號、去空白後，與成分目錄同義詞**完全比對**，不做模糊比對。
"""

import csv
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.extraction.engines.base import LabelReading, ReadingRow, ServingReading
from app.schemas.enums import ALLOWED_INGREDIENTS, DoseUnit, IngredientCode, LabelSection, ScopeStatus, Unit
from app.schemas.label import LabelSuggestedIntake, NutrientDraft, ServingInfoDraft

RULE_LAYER_VERSION = "vlm-r1"  # 改規則就要加版本，草稿的 rule_layer_version 會跟著變
# 與 app/catalog_source.py 讀同一份成分目錄；DB 版目錄好了之後兩邊一起換
CATALOG_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples" / "catalog"

# ─── 單位 ───────────────────────────────────────────────────


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def map_unit(raw: str | None) -> Unit | None:
    """單位原文 → Unit。讀不到為 None；看得到但不認得為 OTHER（只允許出現在範圍外成分）。"""
    if not raw:
        return None
    def compact(text: str) -> str:
        text = re.sub(r"\s+", "", text).lower().replace("µ", "μ")
        # 中英並列的寫法：「毫克mg」「微克mcg」「毫克mg NE」→ 只留中文單位
        return re.sub(r"^(毫克)mg|^(微克)(?:mcg|μg|ug)|^(公克)g|^(大卡)kcal", lambda m: next(g for g in m.groups() if g), text)

    # 先看括號裡是不是 α-TE／NE（「毫克(α-TE)」），再去括號（「微克(800IU)」的括號只是說明）
    for u in (compact(re.sub(r"[()（）]", "", _norm(raw))), compact(_strip_parens(_norm(raw)))):
        if re.fullmatch(r"(mg|毫克)(α-?te|a-?te|ate)", u):
            return Unit.MG_ATE
        if re.fullmatch(r"(mg|毫克)ne", u):
            return Unit.MG_NE
    table = {
        "mg": Unit.MG, "毫克": Unit.MG,
        "μg": Unit.UG, "ug": Unit.UG, "mcg": Unit.UG, "微克": Unit.UG,
        "g": Unit.G, "公克": Unit.G, "克": Unit.G,
        "kcal": Unit.KCAL, "大卡": Unit.KCAL, "千卡": Unit.KCAL,
        "iu": Unit.IU, "國際單位": Unit.IU,
    }
    return table.get(u, Unit.OTHER)


# 「粒」「顆」可能是錠、膠囊或軟膠囊，無法判定 → 留空讓使用者選
_DOSE_UNITS = {
    "錠": DoseUnit.TABLET, "片": DoseUnit.TABLET, "膠囊": DoseUnit.CAPSULE, "軟膠囊": DoseUnit.SOFTGEL,
    "包": DoseUnit.SACHET, "匙": DoseUnit.SCOOP, "毫升": DoseUnit.ML, "ml": DoseUnit.ML, "滴": DoseUnit.DROP,
    "軟糖": DoseUnit.GUMMY,
}


def serving_info(serving: ServingReading | None, image_id: str) -> ServingInfoDraft:
    """每一份量。轉接器標了 needs_review（數值是文字、取了第一個數字）時不採用那個數字：
    ServingInfoDraft 沒有「需要使用者確認」欄位，所以照「不確定的值留空、不猜」的原則留空；
    serving_size 是核對時必填的欄位，留空核對頁就會要使用者填。位置框保留，核對頁仍能標出在照片上的位置。"""
    if serving is None:
        return ServingInfoDraft()
    size = None if serving.needs_review else serving.serving_size
    unit = _DOSE_UNITS.get(_norm(serving.dose_unit_raw or "").lower()) if size else None
    return ServingInfoDraft(serving_size=size, dose_unit=unit, source_image_id=image_id, bbox=serving.bbox)


def suggested_intake(raw: str | None) -> LabelSuggestedIntake | None:
    """只解析明確寫出「每日 N 次」「每次 M」的部分；「每日 3 顆」分不出是一次 3 顆還是 3 次各 1 顆，不猜。"""
    if not raw:
        return None
    text = _norm(raw)
    times = re.search(r"每日\s*(\d+(?:\.\d+)?)\s*次", text)
    amount = re.search(r"每次\s*(\d+(?:\.\d+)?)", text)
    return LabelSuggestedIntake(
        raw_text=raw,
        times_per_day=float(times.group(1)) if times else None,
        amount_per_time=float(amount.group(1)) if amount else None,
    )


# ─── 名稱標準化 ─────────────────────────────────────────────


def _key(text: str) -> str:
    return re.sub(r"\s+", "", _norm(text)).lower()


def _strip_parens(text: str) -> str:
    previous = None
    while previous != text:
        previous, text = text, re.sub(r"[(（\[【][^()（）\[\]【】]*[)）\]】]", "", text)
    return text


def _parens(text: str) -> list[str]:
    return re.findall(r"[(（\[【]([^()（）\[\]【】]*)[)）\]】]", text)


# 化合物名 → (成分, 型態代碼)。只收型態代碼已在目錄使用、規則表會用到，或 supplement-label-output.md 列出的。
# 葡萄糖胺只有鹽酸鹽有型態代碼（小組 spec「型態代碼」）；硫酸鹽認得是葡萄糖胺，但不填型態
_COMPOUNDS = {
    "碳酸鈣": ("calcium", "calcium_carbonate"), "檸檬酸鈣": ("calcium", "calcium_citrate"),
    "葡萄糖胺鹽酸鹽": ("glucosamine", "glucosamine_hcl"), "鹽酸葡萄糖胺": ("glucosamine", "glucosamine_hcl"),
    "胺基葡萄糖鹽酸鹽": ("glucosamine", "glucosamine_hcl"),
    "葡萄糖胺硫酸鹽": ("glucosamine", None), "硫酸葡萄糖胺": ("glucosamine", None),
    "菸鹼酸": ("niacin", "nicotinic_acid"), "菸鹼醯胺": ("niacin", "niacinamide"),
}


@dataclass(frozen=True)
class Names:
    synonyms: dict[str, IngredientCode]
    out_of_scope: frozenset[str]
    version: str


@lru_cache
def load_names(catalog_dir: Path = CATALOG_DIR) -> Names:
    """同義詞表 ＝ ingredients.csv 的 synonyms ＋ out_of_scope_names.csv。版本 ＝ 兩檔內容的雜湊。"""
    ing_path, oos_path = catalog_dir / "ingredients.csv", catalog_dir / "out_of_scope_names.csv"
    digest = hashlib.sha256(ing_path.read_bytes() + oos_path.read_bytes()).hexdigest()[:12]
    synonyms: dict[str, IngredientCode] = {}
    with ing_path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            for name in row["synonyms"].split("|"):
                synonyms[_key(name)] = IngredientCode(row["code"])
    with oos_path.open(encoding="utf-8-sig") as f:
        out = frozenset(_key(r["name"]) for r in csv.DictReader(f))
    return Names(synonyms=synonyms, out_of_scope=out, version=f"syn-{digest}")


def _candidates(raw_name: str) -> list[str]:
    """完全比對的候選：去括號後整串、第一段、最後一段、第一個空白後的部分（中英並列）。
    不拿中間的片段比對，免得「高效 鈣 配方」這類文字只因含「鈣」就被判成鈣。"""
    base = _strip_parens(_norm(raw_name))
    parts = [p for p in re.split(r"\s+", base) if p]
    tail = base.split(None, 1)[1] if len(parts) > 1 else ""
    return [_key(c) for c in [base, parts[0] if parts else "", parts[-1] if parts else "", tail] if c]


@dataclass(frozen=True)
class NameMatch:
    code: IngredientCode | None
    form_code: str | None
    form_raw: str | None
    known_out_of_scope: bool
    elemental_from_name: bool  # 「鈣(碳酸鈣)」：數字本身就是元素量


def match_name(raw_name: str, names: Names) -> NameMatch:
    for cand in _candidates(raw_name):
        if cand in names.synonyms:
            code = names.synonyms[cand]
            form_raw = next((p for p in _parens(_norm(raw_name)) if _key(p) in _COMPOUNDS), None)
            form_code = _COMPOUNDS[_key(form_raw)][1] if form_raw else None
            form_code = form_code or _special_form(code, raw_name)
            # 「鈣(碳酸鈣)」的數字是元素量；允許成分（「葡萄糖胺(葡萄糖胺鹽酸鹽)」）沒有元素量
            elemental = form_raw is not None and code not in ALLOWED_INGREDIENTS
            return NameMatch(code, form_code, form_raw, False, elemental)
        if cand in _COMPOUNDS:
            code, form = _COMPOUNDS[cand]
            return NameMatch(IngredientCode(code), form, _strip_parens(_norm(raw_name)).strip(), False, False)
    form = _special_form(None, raw_name)
    if form in ("epa", "dha", "n3_total", "fish_oil"):
        return NameMatch(IngredientCode.OMEGA_3, form, None, False, False)
    if form == "monacolin_k":
        return NameMatch(IngredientCode.RED_YEAST_RICE, form, None, False, False)
    known = any(c in names.out_of_scope for c in _candidates(raw_name))
    return NameMatch(None, None, None, known, False)


_N3_TOTAL = re.compile(r"ω-?3|omega-?3|n-?3\s*(?:多元)?(?:不飽和)?脂肪酸")
# 英文要整個字對上，避免 repair、Hepatica 這類字裡的 epa 被當成魚油
_MONACOLIN = re.compile(r"(?<![a-z])monacolin(?:k)?(?![a-z])|莫納可林")
_EPA = re.compile(r"(?<![a-z])epa(?![a-z])|二十碳五烯酸")
_DHA = re.compile(r"(?<![a-z])dha(?![a-z])|二十二碳六烯酸")
_HCL = re.compile(r"鹽酸|\bhcl\b|hydrochloride")


def _omega_form(text: str, code: IngredientCode | None) -> str | None:
    if _EPA.search(text):
        return "epa"
    if _DHA.search(text):
        return "dha"
    if _N3_TOTAL.search(text):
        return "n3_total"  # 標示寫 ω-3 脂肪酸總量（不是魚油總量）
    if code is IngredientCode.OMEGA_3 and "魚油" in text:
        return "fish_oil"
    return None


def _special_form(code: IngredientCode | None, raw_name: str) -> str | None:
    """型態代碼（supplement-label-output.md「型態代碼」）：魚油 epa／dha／fish_oil／n3_total、
    紅麴 monacolin_k、葡萄糖胺 glucosamine_hcl。沒寫明型態時為 None。"""
    text = _norm(raw_name).lower()
    if code in (None, IngredientCode.OMEGA_3):
        # 先看括號外：「魚油(含EPA 18%)」是魚油總量，括號裡的 EPA 只是說明
        form = _omega_form(_strip_parens(text), code) or _omega_form(text, code)
        if form:
            return form
    if code in (None, IngredientCode.RED_YEAST_RICE) and _MONACOLIN.search(text):
        return "monacolin_k"
    if code is IngredientCode.GLUCOSAMINE and _HCL.search(text):
        return "glucosamine_hcl"
    return None


# ─── 非成分列過濾（#23 的基本版）──────────────────────────────

_NOT_INGREDIENT = re.compile(
    r"^(每一?份量|本包裝含|每份|每日參考值|營養標示|營養成分|成分|其他成分|內容物|內容量|淨重|容量|保存|有效日期|批號|"
    r"產地|原產地|製造|進口|食品業者|負責廠商|公司|地址|電話|服務專線|注意事項|食用方法|建議食用|警語|品名)"
    r"|^[*＊^©]"  # 註腳、商標聲明
    r"|有限公司|專線|電話|投保|trade\s*mark|©"
    r"|^\d+(\.\d+)?\s*(錠|粒|顆|包|膠囊)$",  # 「95錠」這類包裝數量
    re.IGNORECASE,
)


def is_ingredient_row(row: ReadingRow) -> bool:
    """非成分列：標題、公司資訊、註腳；以及正面文案或其他區塊裡沒有數值的列（行銷文字，不是成分資料）。"""
    name = _norm(row.raw_name)
    if not name or _NOT_INGREDIENT.search(name):
        return False
    return not (row.label_section in (LabelSection.FRONT, LabelSection.OTHER) and row.amount is None)


# ─── 一列成分 ──────────────────────────────────────────────

_ELEMENTAL = re.compile(r"含(?:純|元素)?(鈣|鎂|鐵|鋅|鉀)\s*(\d+(?:\.\d+)?)\s*(mg|毫克)", re.IGNORECASE)


def build_rows(
    readings: list[tuple[str, LabelReading]], names: Names
) -> list[NutrientDraft]:
    """所有圖的列依序整理。範圍判定依區塊（supplement-label-output.md「範圍判定」）：
    - 營養標示方框：同義詞命中 → 範圍內；在範圍外名稱表 → 範圍外；都沒有 → 無法確認，要使用者確認
    - 成分欄：只有允許成分（紅麴、葡萄糖胺、魚油）算範圍內；其餘一律範圍外
      （目標營養素的原料由營養標示方框那列代表；若照「不認得就無法確認」，一張標示會多出二三十個要確認的賦形劑）
    - 其他區塊：同義詞命中但營養標示方框已有同一成分 → 範圍外，避免重複計算
    """
    table_codes = {
        m.code
        for _, reading in readings
        for row in reading.rows
        if row.label_section is LabelSection.NUTRITION_TABLE and is_ingredient_row(row)
        for m in [match_name(row.raw_name, names)]
        if m.code is not None
    }
    drafts: list[NutrientDraft] = []
    for image_id, reading in readings:
        for row in reading.rows:
            if not is_ingredient_row(row):
                continue
            drafts.append(_row(row, image_id, f"r{len(drafts) + 1:02d}", names, table_codes))
    return drafts


def _row(row: ReadingRow, image_id: str, row_id: str, names: Names, table_codes: set) -> NutrientDraft:
    m = match_name(row.raw_name, names)
    unit = map_unit(row.unit_raw)
    section = row.label_section
    code: IngredientCode | None = m.code
    if section is LabelSection.NUTRITION_TABLE:
        scope = ScopeStatus.IN_SCOPE if code else ScopeStatus.OUT_OF_SCOPE if m.known_out_of_scope else ScopeStatus.UNRESOLVED
    elif section is LabelSection.INGREDIENT_LIST:
        scope = ScopeStatus.IN_SCOPE if code in ALLOWED_INGREDIENTS else ScopeStatus.OUT_OF_SCOPE
    elif code is not None and code not in ALLOWED_INGREDIENTS and code in table_codes:
        scope = ScopeStatus.OUT_OF_SCOPE
    elif code is not None:
        scope = ScopeStatus.IN_SCOPE
    else:
        scope = ScopeStatus.OUT_OF_SCOPE if m.known_out_of_scope or _mentions_table_nutrient(row.raw_name, names, table_codes) else ScopeStatus.UNRESOLVED
    in_scope = scope is ScopeStatus.IN_SCOPE
    if not in_scope:
        code = None
    # 轉接器做過數值容錯（「11±2.0」取 11）的列：數字不一定對，一律要使用者確認
    needs_user = scope is ScopeStatus.UNRESOLVED or row.needs_review
    if in_scope and unit is Unit.OTHER:
        unit, needs_user = None, True  # 範圍內不可為 other：留空讓使用者選
    if in_scope and section is LabelSection.NUTRITION_TABLE and (row.amount is None or unit is None):
        needs_user = True
    stated = None
    if in_scope and row.amount is not None:
        found = _ELEMENTAL.search(_norm(row.raw_name))
        if found and map_unit(found.group(3)) is unit:
            stated = float(found.group(2))
        elif m.elemental_from_name:
            stated = row.amount
    return NutrientDraft(
        row_id=row_id,
        raw_name=row.raw_name,
        label_section=section,
        source_image_id=image_id,
        bbox=row.bbox,
        standard_code=code,
        scope_status=scope,
        nutrient_form_raw=m.form_raw if in_scope else None,
        nutrient_form_code=m.form_code if in_scope else None,
        per_serving=row.amount,
        unit=unit,
        stated_elemental_amount=stated,
        percent_dv=row.percent_dv,
        requires_user_input=needs_user,
    )


def _mentions_table_nutrient(raw_name: str, names: Names, table_codes: set) -> bool:
    """「天然海藻鈣(含32%鈣)」這類列：括號裡提到的營養素已在營養標示方框，算範圍外，避免重複計算。"""
    for inner in _parens(_norm(raw_name)):
        token = re.sub(r"^含|[\d.%％\s]", "", inner)
        if _key(token) in names.synonyms and names.synonyms[_key(token)] in table_codes:
            return True
    return False
