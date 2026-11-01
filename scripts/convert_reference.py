"""把 nutrition-agent 已審定的參考資料轉成 g4 格式，寫到 data/catalog/ 與 data/sources/。

用法：uv run python scripts/convert_reference.py --source C:/Project/nutrition-agent

輸出固定排序、固定換行（LF），重跑後 git diff 應為空。只讀來源專案，不改它。
`docs/schemas/examples/catalog/` 的 known_conditions、drug_classes、drug_nutrient_doses
與商品名當作 g4 自己的底稿一起讀入（代碼以 g4 的 enum 為準）。
"""

import argparse
import csv
import re
import tomllib
import unicodedata
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "schemas" / "examples" / "catalog"
OUT = ROOT / "data" / "catalog"
SOURCES_OUT = ROOT / "data" / "sources"
VERSION = "2026.11.1"
RETRIEVED_AT = "2026-10-19"  # nutrition-agent 抓取原文檔的日期（NIH 文件本身沒有標記，以此為準）

CLASS_CODE_MAP = {
    "sglt2_inhibitor": "sglt2",
    "cholesterol_absorption_inhibitor": "ezetimibe",
    "prescription_glucosamine": "glucosamine_rx",
    "bzd_z_drug": "bzd_zdrug",
    "melatonin": "melatonin_rx",
    "h2_receptor_antagonist": "h2ra",
    "calcium_magnesium_antacid": "antacid_laxative",
}
GROUP_MAP = {"type2_diabetes": "t2dm", "hyperlipidemia": "dyslipidemia"}
UNIT_MAP = {"mg": "mg", "ug": "ug", "mg_alpha_te": "mg_ate", "mg_ne": "mg_ne", "ug_dfe": "ug"}
UL_SCOPE_MAP = {
    "non_food": "supplement_only",
    "supplement_and_fortified": "supplement_only",
    "includes_diet": "total_intake",
}
AGE_BANDS = {(19, 30): "19-30", (31, 50): "31-50", (51, 70): "51-70", (71, None): "71+"}
STATUS_MAP = {"approved": "reviewed", "retired": "retired", "draft": "draft"}
SOURCE_MAP = {"nih_ods_hp": "nih_ods", "nccih": "nccih"}
CURATED_BY = "nutrition-agent（LLM 協助草擬）"
REVIEWER = "PolunChao"
# 2026-10-20 人工審查補過條件的規則（rules.toml 檔頭註記）；其餘為 2026-10-19
REVIEWED_1020 = {
    "ppi-magnesium", "ppi-iron", "ppi-vitamin-b12", "h2-vitamin-b12",
    "thiazide-vitamin-d", "acei-arb-potassium",
}  # fmt: skip
POPULATIONS = {
    "metformin-vitamin-b12": "服用 Metformin 者",
    "ppi-vitamin-b12": "長期服用質子幫浦抑制劑者",
    "h2-vitamin-b12": "長期服用 H2 受體拮抗劑者",
    "ppi-magnesium": "長期（通常超過一年）服用質子幫浦抑制劑者",
    "ppi-iron": "服用質子幫浦抑制劑者",
    "ppi-calcium": "服用質子幫浦抑制劑者",
    "thiazide-magnesium": "長期服用利尿劑者",
    "thiazide-potassium": "服用利尿劑者",
    "thiazide-zinc": "服用 Thiazide 類利尿劑者",
    "thiazide-vitamin-d": "服用 Thiazide 類利尿劑並補充維生素 D 者",
    "acei-arb-potassium": "服用 ACEI／ARB 者",
    "atorvastatin-vitamin-d": "服用 Atorvastatin 者",
    "simvastatin-vitamin-d": "服用 Simvastatin 者",
    "biguanide-niacin": "服用降血糖藥並補充高劑量菸鹼酸者",
    "insulin-niacin": "服用降血糖藥並補充高劑量菸鹼酸者",
    "statin-red-yeast-rice": "服用 Statin 類藥物者",
    "glucosamine-rx-duplicate": "服用處方葡萄糖胺者",
}
# g4 新增的草稿規則（只有組長能改成 reviewed）。引文逐字取自 NCCIH 原文檔。
NEW_DRAFT_RULES = [
    {
        "id": "statin-red-yeast-rice",
        "condition_type": "drug_class",
        "condition_code": "statin",
        "ingredient_code": "red_yeast_rice",
        "interaction_type": "pharmacodynamic",
        "requires_supplement_intake": True,
        "advice": "consult_before_combining",
        "reason_zh": "紅麴所含的成分與這類降血脂藥的成分相同，併用等於重複用藥，可能增加肌肉等不良反應的風險。",
        "citations": [
            {
                "source_type": "nccih",
                "document": "sources/nccih/RedYeastRice-NCCIH.md",
                "quote": "Monacolin K is structurally identical to the medicine lovastatin",
            }
        ],
    },
    {
        "id": "glucosamine-rx-duplicate",
        "condition_type": "drug_class",
        "condition_code": "glucosamine_rx",
        "ingredient_code": "glucosamine",
        "interaction_type": "pharmacodynamic",
        "requires_supplement_intake": True,
        "advice": "consult_before_combining",
        "reason_zh": "處方葡萄糖胺與保健食品裡的葡萄糖胺是同一種成分，兩邊都吃會重複攝取。",
        "citations": [
            {
                "source_type": "nccih",
                "document": "sources/nccih/Glucosamine-NCCIH.md",
                "quote": "certain preparations of glucosamine and chondroitin are sold as prescription drugs",
            }
        ],
    },
]
NEW_DRAFT_NOTE = "g4 新增草稿，引文逐字取自 NCCIH 原文檔，待組長審"
RETIRED_NOTE = "退役原因見 reason_zh；完整審查紀錄在 nutrition-agent 的 rules.toml 註解"


def norm_key(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).casefold()


def write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(["" if v is None else v for v in row])


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_commented_csv(path: Path, skip_rows: int = 0) -> list[dict[str, str]]:
    """略過 # 註解行；skip_rows 為註解之後、欄位列之前要丟掉的行數（例如 version 行）。"""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    return list(csv.DictReader(lines[skip_rows:]))


def load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def map_class(code: str) -> str:
    return CLASS_CODE_MAP.get(code, code)


def pipe(values: Sequence[str]) -> str:
    return "|".join(values)


# ─── 成分、DRIs、單位 ───────────────────────────────────────


def build_ingredients(src: Path, scope_by_nutrient: dict[str, str], conv: list[dict]) -> tuple[list[list], list[str]]:
    data = load_toml(src / "ingredients.toml")["ingredient"]
    rows, codes = [], []
    for ing in sorted((i for i in data if i["category"] != "out_of_scope"), key=lambda i: i["sort_order"]):
        code, is_target = ing["code"], ing["category"] == "target_nutrient"
        std = UNIT_MAP[ing["canonical_unit"]] if is_target else None
        accepted: list[str] = [std] if std else []
        for c in conv:
            if c.get("nutrient_code") == code:
                unit = "iu" if c["from_unit"] == "IU" else ("mg" if c["from_unit"].startswith("mg") else c["from_unit"])
                if unit in UNIT_MAP.values() or unit == "iu":
                    accepted.append(unit)
        accepted = list(dict.fromkeys(accepted))
        synonyms = list(dict.fromkeys([ing["display_name_zh"], *ing["synonyms"]]))
        rows.append([code, ing["category"], ing["display_name_zh"], std, pipe(accepted), pipe(synonyms),
                     scope_by_nutrient.get(code)])  # fmt: skip
        codes.append(code)
    return rows, codes


def build_dris(src: Path, nutrients: list[str]) -> tuple[list[list], dict[str, str]]:
    raw = read_commented_csv(src / "dris.csv", skip_rows=1)  # 第一行是 version
    order = {n: i for i, n in enumerate(nutrients)}
    rows: list[list] = []
    scope: dict[str, str] = {}
    for nutrient in nutrients:
        if nutrient not in {r["nutrient_code"] for r in raw}:
            continue  # 允許成分沒有 DRIs
        for sex in ("male", "female"):
            for (lo, hi), band in AGE_BANDS.items():
                def pick(r: dict, kinds: tuple[str, ...]) -> bool:
                    return (
                        r["nutrient_code"] == nutrient and r["kind"] in kinds and r["sex"] in (sex, "any")
                        and int(r["age_min"]) == lo and (int(r["age_max"]) if r["age_max"] else None) == hi
                    )  # fmt: skip

                refs = [r for r in raw if pick(r, ("rda", "ai"))]
                uls = [r for r in raw if pick(r, ("ul",))]
                if len(refs) != 1 or len(uls) != 1:
                    raise SystemExit(f"DRIs 樞紐失敗：{nutrient} {sex} {band}（ref {len(refs)}、ul {len(uls)}）")
                ref, ul = refs[0], uls[0]
                unit = UNIT_MAP[ref["unit"]]
                if UNIT_MAP[ul["unit"]] != unit:
                    raise SystemExit(f"{nutrient} 的 ul 與建議量單位不同")
                if ul["ul_scope"]:
                    scope[nutrient] = UL_SCOPE_MAP[ul["ul_scope"]]
                rows.append([nutrient, sex, band, ref["kind"], ref["value"], ul["value"] or None, unit])
    rows.sort(key=lambda r: (order[r[0]], r[1] != "male", list(AGE_BANDS.values()).index(r[2])))
    return rows, scope


def form_code(from_unit: str) -> str:
    return from_unit.removeprefix("mg_") if from_unit.startswith("mg_") else "all"


def build_conversions(conv: list[dict], targets: set[str]) -> list[list]:
    rows = []
    for c in conv:
        n = c.get("nutrient_code")
        if n not in targets or n == "folate":
            continue  # 葉酸 ug→ug_dfe 在 g4 沒有對應的 Unit，改在 dris-reference-notes 說明
        from_u = "iu" if c["from_unit"] == "IU" else ("mg" if c["from_unit"].startswith("mg_") else c["from_unit"])
        rows.append([n, from_u, UNIT_MAP.get(c["to_unit"], c["to_unit"]), c["factor"], form_code(c["from_unit"]), c["source"]])
    return rows


def build_compounds(src: Path, targets: set[str]) -> list[list]:
    rows = []
    for c in load_toml(src / "compounds.toml")["compound"]:
        if c["nutrient_code"] not in targets:
            continue
        rows.append([c["code"], c["nutrient_code"], c["display_name_zh"], pipe(c["synonyms"]), c["formula"],
                     c["element_ratio"], f"分子量計算：{c['molecular_weight_expr']}"])  # fmt: skip
    return rows


# ─── 藥物 ───────────────────────────────────────────────────


def build_drugs(src: Path) -> tuple[list[list], list[list], set[str]]:
    toml = load_toml(src / "drugs.toml")
    example_classes = {r["drug_class_code"]: r for r in read_csv(EXAMPLES / "drug_classes.csv")}
    example_items = {r["active_ingredient_code"]: r for r in read_csv(EXAMPLES / "drug_items.csv")}
    group_of: dict[str, str] = {}
    class_rows = []
    for c in toml["class"]:
        code = map_class(c["code"])
        group = GROUP_MAP.get(c["group"], c["group"])
        ex = example_classes[code]
        if (ex["role"], ex["menu_group"]) != (c["role"], group):
            raise SystemExit(f"用藥類別 {code} 的角色或分組與 g4 範例不一致")
        group_of[c["code"]] = group
        class_rows.append([code, ex["display_name_zh"], ex["plain_description_zh"], c["role"], group])
    item_rows = []
    for i in toml["ingredient"]:
        group = group_of[i["class_code"]]
        ex = example_items.get(i["code"])
        tradenames = ex["common_tradenames_tw"] if ex else i["name_zh"]
        related = "" if group == "gastrointestinal" else group
        requires_dose = "true" if i["code"] == "magnesium_oxide" else "false"  # 與 drug_nutrient_doses.csv 一致
        item_rows.append([i["code"], i["name_zh"], i["name_en"], map_class(i["class_code"]), tradenames, related, requires_dose])
    # g4 範例裡有、nutrition-agent 沒有的複方項目（例如 losartan_hydrochlorothiazide）照舊保留，
    # 藥名比對（map_item）靠它把複方對到一個項目、一對多類別
    in_toml = {r[0] for r in item_rows}
    for code, ex in example_items.items():
        if code not in in_toml:
            item_rows.append([code, ex["display_name_zh"], ex["english_name"], ex["drug_class_codes"],
                              ex["common_tradenames_tw"], ex["related_conditions"], ex["requires_dose"]])  # fmt: skip
    return class_rows, item_rows, {r[0] for r in item_rows}


def build_drug_products(src: Path, item_codes: set[str]) -> list[list]:
    rows = []
    for r in read_commented_csv(src / "drug_names.csv", skip_rows=1):  # 第一行是 version（TFDA 快照日期）
        codes = [c for c in r["ingredients"].split("|") if c]
        unknown = set(codes) - item_codes
        if unknown:
            raise SystemExit(f"藥名表出現藥物目錄沒有的代碼：{r['name']} → {unknown}")
        rows.append([r["name"], r["lang"], r["ingredients"], r["out_of_scope"]])
    return rows


def build_out_of_scope(src: Path) -> list[list]:
    rows = [[r["name"], r["note"] or None] for r in read_csv(EXAMPLES / "out_of_scope_names.csv")]
    seen = {norm_key(r[0]) for r in rows}
    for ing in load_toml(src / "ingredients.toml")["ingredient"]:
        if ing["category"] != "out_of_scope":
            continue
        for name in (ing["display_name_zh"], *ing["synonyms"]):
            if norm_key(name) not in seen:
                seen.add(norm_key(name))
                rows.append([name, None])
    return rows


# ─── 規則與出處 ─────────────────────────────────────────────


def normalized_with_index(text: str) -> tuple[str, list[int]]:
    """NFKC＋去空白後的字串，以及每個字元在原文的位置（用來回找章節）。"""
    chars, index = [], []
    for pos, ch in enumerate(text):
        for n in unicodedata.normalize("NFKC", ch):
            if not n.isspace():
                chars.append(n)
                index.append(pos)
    return "".join(chars), index


def locate_section(text: str, quote: str) -> str:
    norm, index = normalized_with_index(text)
    at = norm.find("".join(unicodedata.normalize("NFKC", quote).split()))
    if at < 0:
        raise SystemExit(f"引文不在原文檔：{quote[:50]}")
    pos = index[at]
    chain: dict[int, str] = {}
    for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text[:pos], re.MULTILINE):
        level = len(m.group(1))
        chain = {k: v for k, v in chain.items() if k < level}
        chain[level] = m.group(2)
    return " > ".join(v for k, v in sorted(chain.items()) if k >= 2) or (chain.get(1) or "")


def document_meta(path: Path, text: str) -> tuple[str, str | None]:
    """(url, source_version)。NIH 的網址在第一行連結，NCCIH 在開頭註解。"""
    m = re.search(r"來源：(https?://\S+?)（", text) or re.search(
        r"\((https://ods\.od\.nih\.gov/factsheets/[^)#]+)", text
    )
    if not m:
        raise SystemExit(f"{path.name} 找不到網址")
    v = re.search(r"\*\*(?:Last )?Updated:\*\*\s*(.+?)(?:\s*\[|\\|$)", text, re.MULTILINE)
    return m.group(1), (f"Updated: {v.group(1).strip()}" if v else None)


def build_rules(src: Path) -> tuple[list[list], list[list]]:
    raw_rules = load_toml(src / "rules.toml")["rule"] + NEW_DRAFT_RULES
    citation_ids: dict[tuple[str, str], str] = {}
    citation_rows: dict[str, list] = {}
    populations: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    rule_rows = []
    for r in raw_rules:
        ids = []
        for c in r["citations"]:
            doc = c["document"].removeprefix("sources/")
            key = (doc, c["quote"])
            if key not in citation_ids:
                if doc not in texts:
                    texts[doc] = (SOURCES_OUT / doc).read_text(encoding="utf-8")
                cid = f"cit-{len(citation_ids) + 1:04d}"
                citation_ids[key] = cid
                url, version = document_meta(SOURCES_OUT / doc, texts[doc])
                citation_rows[cid] = [cid, SOURCE_MAP[c["source_type"]], None, url,
                                      locate_section(texts[doc], c["quote"]), c["quote"], "", "US",
                                      RETRIEVED_AT, version, doc]  # fmt: skip
                populations[cid] = []
            cid = citation_ids[key]
            if POPULATIONS[r["id"]] not in populations[cid]:
                populations[cid].append(POPULATIONS[r["id"]])
            ids.append(cid)
        status = STATUS_MAP[r.get("status", "draft")]
        is_new = r in NEW_DRAFT_RULES
        reviewed = status != "draft"
        reviewed_at = "2026-10-20" if r["id"] in REVIEWED_1020 else "2026-10-19"
        tier = r["citations"][0]["source_type"]
        rule_rows.append([
            r["id"], r["condition_type"], map_class(r["condition_code"]) if r["condition_type"] == "drug_class" else r["condition_code"],
            r["ingredient_code"], pipe([r["ingredient_form"]] if r.get("ingredient_form") else []),
            r["interaction_type"], str(r["requires_supplement_intake"]).lower(), "true", r["advice"], None,
            r["reason_zh"], pipe(dict.fromkeys(ids)), tier, status,
            "Claude Code（草擬）" if is_new else CURATED_BY,
            REVIEWER if reviewed else None, reviewed_at if reviewed else None,
            NEW_DRAFT_NOTE if is_new else (RETIRED_NOTE if status == "retired" else None),
        ])  # fmt: skip
    for cid, row in citation_rows.items():
        row[6] = "、".join(populations[cid])
    return rule_rows, list(citation_rows.values())


def copy_sources(src: Path) -> None:
    root = src / "knowledge" / "sources"
    for sub, pattern in (("nih_ods", "*-HealthProfessional.md"), ("nccih", "*.md"), ("dris", "*.md")):
        dest = SOURCES_OUT / sub
        dest.mkdir(parents=True, exist_ok=True)
        wanted = {p.name for p in (root / sub).glob(pattern)}
        for stale in dest.glob("*"):
            if stale.name not in wanted:
                stale.unlink()
        for name in sorted(wanted):
            # 換行統一成 LF，不同系統重轉的結果才會一樣
            text = (root / sub / name).read_bytes().replace(b"\r\n", b"\n")
            (dest / name).write_bytes(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="nutrition-agent 專案根目錄")
    src_root: Path = parser.parse_args().source
    data = src_root / "src" / "nutrition_agent" / "reference" / "data"
    conv = load_toml(data / "units.toml")["rule"]

    copy_sources(src_root)
    ing_codes = [i["code"] for i in load_toml(data / "ingredients.toml")["ingredient"] if i["category"] == "target_nutrient"]
    ing_codes.sort(key=lambda c: next(i["sort_order"] for i in load_toml(data / "ingredients.toml")["ingredient"] if i["code"] == c))
    dris_rows, scope = build_dris(data, ing_codes)
    ing_rows, _ = build_ingredients(data, scope, conv)
    targets = set(ing_codes)
    class_rows, item_rows, item_codes = build_drugs(data)
    rule_rows, citation_rows = build_rules(data)

    write_csv(OUT / "known_conditions.csv", ["condition_code", "display_name_zh", "backend_name", "sort_order"],
              [list(r.values()) for r in read_csv(EXAMPLES / "known_conditions.csv")])  # fmt: skip
    write_csv(OUT / "drug_classes.csv", ["drug_class_code", "display_name_zh", "plain_description_zh", "role", "menu_group"], class_rows)
    write_csv(OUT / "drug_items.csv", ["active_ingredient_code", "display_name_zh", "english_name", "drug_class_codes",
              "common_tradenames_tw", "related_conditions", "requires_dose"], item_rows)  # fmt: skip
    write_csv(OUT / "drug_nutrient_doses.csv", ["active_ingredient_code", "dose_option_mg", "nutrient_code",
              "elemental_mg_per_unit", "source"],
              [[r["active_ingredient_code"], r["dose_option_mg"], r["nutrient_code"], r["elemental_mg_per_unit"],
                "氧化鎂含鎂比率 0.603（compound_ratios.csv）× 劑量，四捨五入到小數 1 位"]
               for r in read_csv(EXAMPLES / "drug_nutrient_doses.csv")])  # fmt: skip
    write_csv(OUT / "drug_products.csv", ["name", "lang", "active_ingredient_codes", "out_of_scope_ingredients"],
              build_drug_products(data, item_codes))  # fmt: skip
    write_csv(OUT / "ingredients.csv", ["code", "category", "display_name_zh", "standard_unit", "accepted_units",
              "synonyms", "ul_scope"], ing_rows)  # fmt: skip
    write_csv(OUT / "out_of_scope_names.csv", ["name", "note"], build_out_of_scope(data))
    write_csv(OUT / "dris_values.csv", ["nutrient_code", "sex", "age_band", "reference_type", "reference_value",
              "ul_value", "unit"], dris_rows)  # fmt: skip
    write_csv(OUT / "compound_ratios.csv", ["compound_code", "nutrient_code", "display_name_zh", "synonyms", "formula",
              "ratio", "source"], build_compounds(data, targets))  # fmt: skip
    write_csv(OUT / "conversion_factors.csv", ["nutrient_code", "from_unit", "to_unit", "factor", "applies_to_form",
              "source"], build_conversions(conv, targets))  # fmt: skip
    write_csv(OUT / "rules.csv", ["rule_id", "condition_type", "condition_code", "ingredient_code",
              "ingredient_form_codes", "interaction_type", "requires_supplement_intake",
              "requires_professional_review", "advice_code", "separation_hours", "reason_zh", "citation_ids",
              "evidence_tier", "status", "curated_by", "reviewed_by", "reviewed_at", "curation_note"], rule_rows)  # fmt: skip
    write_csv(OUT / "citations.csv", ["citation_id", "source", "source_record_id", "url", "section", "quote",
              "population", "jurisdiction", "retrieved_at", "source_version", "document_path"], citation_rows)  # fmt: skip
    (OUT / "VERSION").write_text(VERSION + "\n", encoding="utf-8", newline="\n")
    print(f"完成：規則 {len(rule_rows)} 條、引文 {len(citation_rows)} 段、藥名 {len(item_rows)} 個有效成分")


if __name__ == "__main__":
    main()
