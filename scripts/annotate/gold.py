"""把雙盲標註、人工裁決與抽查結果轉成標準答案（issue 03）。範圍狀態與型態代碼的規則見 supplement-label-output.md。

三個步驟：
1. adjudicate：兩份標註 ＋ 不一致清單的裁決 ＋ 抽查錯誤的更正 → 每張照片一份裁決後的標註
2. draft_name_map：列出每個（名稱, 區塊），附上範圍狀態與標準代碼的建議，交給人確認。
   範圍狀態與標準代碼是名稱標準化（#09）的正確答案，必須由人決定，不能拿程式的對映結果當答案
3. build_gold：裁決後的標註 ＋ 人確認過的名稱對照表 → 每個產品一份辨識草稿結構的標準答案
"""

import csv
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.extraction.textnorm import compact, strip_parenthetical
from app.schemas.enums import IngredientCode, LabelSection, ScopeStatus
from app.schemas.label import ExtractionDraft
from scripts.annotate.compare import ROW_PRESENCE, SERVING_ROW, _pair_rows, compare
from scripts.annotate.schema import AnnotatedRow, AnnotatedServing, Annotation

DELETE = "刪除"
NULL = "null"
GOLD_VERSION = "gold-annotation"
GOLD_EXTRACTED_AT = "2026-10-05T00:00:00+08:00"  # 比較集標準答案的定稿日
_FLOAT_FIELDS = {"per_serving", "percent_dv", "stated_elemental_amount", "serving_size"}
_PRODUCT_NS = uuid.UUID("6f1c6a3e-3b1e-4c0e-9d7a-1f0e2a6b0c01")  # 產品編號 → 固定的 product_id


class GoldError(Exception):
    """裁決或對照表不完整，無法產生標準答案。"""


# ── 1. 合併裁決 ─────────────────────────────────────────────────


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _typed(field: str, value: str, where: tuple[str, str, str] | None = None):
    if value in ("", NULL):
        return None
    if field not in _FLOAT_FIELDS:
        return value
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not math.isfinite(number):  # NaN、inf 也不算合法數字
        raise GoldError(f"{where or field} 應該填數字（或 null），卻填了「{value}」")
    return number


def adjudicate(
    a: dict[str, Annotation],
    b: dict[str, Annotation],
    disagreements: list[dict[str, str]],
    spot_checks: list[dict[str, str]],
    corrections: list[dict[str, str]],
) -> dict[str, Annotation]:
    """回傳照片編號 → 裁決後的標註。不一致沒裁決、抽查判錯卻沒有更正，都會報錯。"""
    if a.keys() != b.keys():  # 雙盲標註不完整：少一邊的照片不能默默丟掉
        missing_images = sorted(a.keys() ^ b.keys())
        raise GoldError(f"兩位標註者的照片不一致，缺：{', '.join(missing_images)}")
    ruling = {(r["image_id"], r["row"], r["field"]): r["adjudicated"].strip() for r in disagreements}
    expected = {(f.image_id, f.row, f.field) for f in compare(a, b).disagreements}
    unlisted = sorted(expected - ruling.keys())
    if unlisted:  # 不一致清單過期或漏列時，不能默默採用其中一邊的值
        raise GoldError(f"有 {len(unlisted)} 項不一致不在裁決清單裡（請重新執行 compare），例如 {unlisted[0]}")
    obsolete = sorted(ruling.keys() - expected)
    if obsolete:  # 反方向：清單裡的項目現在已經不是不一致（例如重新標註後），舊裁決可能套到別列
        raise GoldError(f"有 {len(obsolete)} 項裁決對應的不一致已經不存在（請重新執行 compare），例如 {obsolete[0]}")
    missing = [k for k, v in ruling.items() if not v]
    if missing:
        raise GoldError(f"還有 {len(missing)} 項不一致沒有裁決，例如 {missing[0]}")
    fixes = {(r["image_id"], r["row"], r["field"]): r["value"].strip() for r in corrections}
    wrong = [(r["image_id"], r["row"], r["field"]) for r in spot_checks if r.get("verdict", "").strip() == "錯"]
    unfixed = [k for k in wrong if not fixes.get(k)]  # 更正值留白不算；要清空請明確填 null
    if unfixed:
        raise GoldError(f"抽查判錯的 {len(unfixed)} 項沒有更正值（填在 corrections.csv），例如 {unfixed[0]}")
    decided = {**ruling, **fixes}

    def value(image_id: str, label: str, field: str, agreed):
        key = (image_id, label, field)
        return _typed(field, decided[key], key) if key in decided else agreed

    gold: dict[str, Annotation] = {}
    for image_id in sorted(a.keys() & b.keys()):
        sa = a[image_id].serving  # 一致的欄位取哪邊都一樣；不一致的由裁決決定
        serving = AnnotatedServing.model_validate(
            {f: value(image_id, SERVING_ROW, f, getattr(sa, f)) for f in AnnotatedServing.model_fields}
        )
        pairs, leftovers = _pair_rows(a[image_id].rows, b[image_id].rows)
        rows = []
        for label, row_a, row_b in pairs + leftovers:
            if row_a is None or row_b is None:
                if decided.get((image_id, label, ROW_PRESENCE)) == DELETE:
                    continue
            base = row_a or row_b
            fields = {f: value(image_id, label, f, getattr(base, f)) for f in AnnotatedRow.model_fields}
            rows.append(AnnotatedRow.model_validate(fields))
        gold[image_id] = Annotation(serving=serving, rows=rows)
    return gold


# ── 2. 名稱對照表草稿 ───────────────────────────────────────────

NAME_MAP_FIELDS = ["raw_name", "label_section", "images", "group", "scope_status", "standard_code", "nutrient_form_code", "note"]


@dataclass(frozen=True)
class Suggestion:
    group: str  # in_scope（建議範圍內）、check（待確認）、out_of_scope（建議範圍外）
    scope: ScopeStatus
    code: str | None = None
    form: str | None = None
    note: str = ""


def _synonyms(ingredients_csv: Path) -> dict[str, str]:
    table = {}
    for row in _read(ingredients_csv):
        for name in row["synonyms"].split("|"):
            if name.strip():
                table[compact(name).lower()] = row["code"]
    return table


def _allowed(name: str) -> Suggestion | None:
    """允許成分不論出現在哪個區塊都是範圍內（supplement-label-output.md「範圍判定」）。"""
    text = compact(name).lower()
    if "monacolin" in text:
        return Suggestion("in_scope", ScopeStatus.IN_SCOPE, IngredientCode.RED_YEAST_RICE, "monacolin_k")
    if "紅麴" in text:
        return Suggestion("in_scope", ScopeStatus.IN_SCOPE, IngredientCode.RED_YEAST_RICE)
    if "葡萄糖胺" in text:
        form = "glucosamine_hcl" if "鹽酸鹽" in text else None
        return Suggestion("in_scope", ScopeStatus.IN_SCOPE, IngredientCode.GLUCOSAMINE, form)
    if re.search(r"\bepa\b|\(epa\)|二十碳五烯酸", text):
        return Suggestion("in_scope", ScopeStatus.IN_SCOPE, IngredientCode.OMEGA_3, "epa")
    if re.search(r"\bdha\b|\(dha\)|二十二碳六烯酸", text):
        return Suggestion("in_scope", ScopeStatus.IN_SCOPE, IngredientCode.OMEGA_3, "dha")
    if "魚油" in text:
        return Suggestion("in_scope", ScopeStatus.IN_SCOPE, IngredientCode.OMEGA_3, "fish_oil")
    if "ω-3" in text or "omega-3" in text or "n-3" in text:
        return Suggestion(
            "check", ScopeStatus.IN_SCOPE, IngredientCode.OMEGA_3, "n3_total",
            "ω-3 脂肪酸總量不是魚油總量；spec 只定義 epa／dha／fish_oil 三種型態，這裡暫用 n3_total",
        )  # fmt: skip
    return None


def suggest(name: str, section: str, synonyms: dict[str, str], table_codes: set[str]) -> Suggestion:
    allowed = _allowed(name)
    if allowed:
        return allowed
    if section == LabelSection.INGREDIENT_LIST:
        return Suggestion("out_of_scope", ScopeStatus.OUT_OF_SCOPE, note="成分欄的原料或賦形劑（範圍判定見 supplement-label-output.md）")
    core = compact(strip_parenthetical(name.split(" ")[0])).lower()  # 「維生素B12 Vitamin B12」取中文部分
    code = synonyms.get(core)
    if code and section == LabelSection.NUTRITION_TABLE:
        return Suggestion("in_scope", ScopeStatus.IN_SCOPE, code)
    if code:
        return Suggestion("check", ScopeStatus.IN_SCOPE, code, note="不在營養標示表，請確認是否為該營養素的含量")
    if "含" in name:
        hit = next((c for n, c in synonyms.items() if n and n in compact(name).lower()), None)
        if hit:
            dup = hit in table_codes
            return Suggestion(
                "check", ScopeStatus.OUT_OF_SCOPE if dup else ScopeStatus.IN_SCOPE, hit if not dup else None,
                note=("營養標示表已有這個營養素，標範圍內會重複計算，建議範圍外" if dup
                      else "化合物寫明所含營養素，營養標示表沒有這個營養素，建議範圍內"),
            )  # fmt: skip
    return Suggestion("out_of_scope", ScopeStatus.OUT_OF_SCOPE, note="不是第一版目標營養素或允許成分")


def draft_name_map(gold: dict[str, Annotation], ingredients_csv: Path) -> list[dict[str, str]]:
    synonyms = _synonyms(ingredients_csv)
    seen: dict[tuple[str, str], dict[str, str]] = {}
    for image_id, annotation in gold.items():
        table_codes = {
            code
            for r in annotation.rows
            if r.label_section == LabelSection.NUTRITION_TABLE
            and (code := synonyms.get(compact(strip_parenthetical(r.raw_name.split(" ")[0])).lower()))
        }
        for row in annotation.rows:
            key = (row.raw_name, row.label_section.value)
            if key in seen:
                seen[key]["images"] += f" {image_id}"
                continue
            s = suggest(row.raw_name, row.label_section, synonyms, table_codes)
            seen[key] = {
                "raw_name": row.raw_name,
                "label_section": row.label_section.value,
                "images": image_id,
                "group": s.group,
                "scope_status": s.scope.value,
                "standard_code": s.code or "",
                "nutrient_form_code": s.form or "",
                "note": s.note,
            }
    order = {"check": 0, "in_scope": 1, "out_of_scope": 2}
    return sorted(seen.values(), key=lambda r: (order[r["group"]], r["images"].split()[0], r["raw_name"]))


def write_name_map(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=NAME_MAP_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ── 3. 產生標準答案 ─────────────────────────────────────────────


def build_gold(gold: dict[str, Annotation], name_map: list[dict[str, str]], sources: list[dict[str, str]]) -> dict[str, ExtractionDraft]:
    """回傳產品編號 → 標準答案。同一產品的多張照片依 sources.csv 的 product_id 合在一份裡，列依照片順序排列。"""
    mapping = {(r["raw_name"], r["label_section"]): r for r in name_map}
    product_of = {r["image_id"]: r for r in sources}
    by_product: dict[str, list[str]] = {}
    for image_id in sorted(gold):
        if image_id not in product_of:
            raise GoldError(f"{image_id} 不在 sources.csv")
        by_product.setdefault(product_of[image_id]["product_id"], []).append(image_id)

    drafts = {}
    for product, images in by_product.items():
        nutrients, serving_info = [], {}
        for image_id in images:
            annotation = gold[image_id]
            if not serving_info and (annotation.serving.serving_size or annotation.serving.dose_unit):
                serving_info = {"source_image_id": image_id, **annotation.serving.model_dump(mode="json")}
            for row in annotation.rows:
                m = mapping.get((row.raw_name, row.label_section.value))
                if m is None:
                    raise GoldError(f"名稱對照表沒有（{row.raw_name}, {row.label_section.value}）")
                nutrients.append(
                    {
                        "row_id": f"r{len(nutrients) + 1:02d}",
                        "raw_name": row.raw_name,
                        "label_section": row.label_section.value,
                        "source_image_id": image_id,
                        "standard_code": m["standard_code"] or None,
                        "scope_status": m["scope_status"],
                        "nutrient_form_code": m["nutrient_form_code"] or None,
                        "per_serving": row.per_serving,
                        "unit": row.unit,
                        "stated_elemental_amount": row.stated_elemental_amount,
                        "percent_dv": row.percent_dv,
                    }
                )
        serving = serving_info or {"source_image_id": images[0]}
        drafts[product] = ExtractionDraft.model_validate(
            {
                "product_id": str(uuid.uuid5(_PRODUCT_NS, product)),
                "product_name": product_of[images[0]]["product_name"] or None,
                "source_images": [{"image_id": i, "quality_status": "accepted"} for i in images],
                "serving_info": {
                    "serving_size": serving.get("serving_size"),
                    "dose_unit": serving.get("dose_unit"),
                    "source_image_id": serving["source_image_id"],
                },
                "nutrients": nutrients,
                "extraction_meta": {
                    "ocr_version": GOLD_VERSION,
                    "rule_layer_version": GOLD_VERSION,
                    "synonym_table_version": GOLD_VERSION,
                    "extracted_at": GOLD_EXTRACTED_AT,  # 固定時間：重跑不會讓 10 份檔案都出現差異
                },
            }
        )
    return drafts
