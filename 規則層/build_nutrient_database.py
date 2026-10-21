"""從規則.md 和營養品評估.py 產生獨立的 JSON 名稱／劑量資料。"""

import ast
import json
import re
from collections import OrderedDict
from pathlib import Path


SOURCE_DIR = Path(r"C:\Users\student\Desktop\aipe04_project_g4\規則層")
OUTPUT_DIR = Path(r"C:\Users\student\Documents\Codex\2026-10-04\new-chat\outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

AGE_BANDS = ["19-30", "31-50", "51-70", "71+"]
ENGLISH = {
    "蛋白質": ("Protein", []),
    "碳水化合物": ("Carbohydrate", ["Carbohydrates"]),
    "膳食纖維": ("Dietary fiber", ["Dietary fibre", "Fiber"]),
    "脂質": ("Total fat", ["Fat", "Lipids"]),
    "飽和脂肪酸": ("Saturated fatty acids", ["Saturated fat"]),
    "n-6 多元不飽和脂肪酸": ("Omega-6 polyunsaturated fatty acids", ["n-6 polyunsaturated fatty acids"]),
    "n-3 多元不飽和脂肪酸": ("Omega-3 polyunsaturated fatty acids", ["n-3 polyunsaturated fatty acids"]),
    "反式脂肪酸": ("Trans fatty acids", ["Trans fat"]),
    "維生素 A": ("Vitamin A", []),
    "維生素 D": ("Vitamin D", []),
    "維生素 E": ("Vitamin E", []),
    "維生素 K": ("Vitamin K", []),
    "維生素 C": ("Vitamin C", []),
    "維生素 B1": ("Vitamin B1", ["Thiamin", "Thiamine"]),
    "維生素 B2": ("Vitamin B2", ["Riboflavin"]),
    "菸鹼素": ("Niacin", ["Vitamin B3"]),
    "維生素 B6": ("Vitamin B6", []),
    "維生素 B12": ("Vitamin B12", []),
    "葉酸": ("Folate", []),
    "膽素": ("Choline", []),
    "生物素": ("Biotin", []),
    "泛酸": ("Pantothenic acid", ["Vitamin B5"]),
    "鈣": ("Calcium", []),
    "磷": ("Phosphorus", []),
    "鎂": ("Magnesium", []),
    "鐵": ("Iron", []),
    "鋅": ("Zinc", []),
    "碘": ("Iodine", []),
    "硒": ("Selenium", []),
    "氟": ("Fluoride", []),
    "鈉": ("Sodium", []),
    "鉀": ("Potassium", []),
    "紅麴": ("Red yeast rice", []),
    "葡萄糖胺": ("Glucosamine", []),
    "魚油": ("Fish oil", []),
}
EXTRAS = {"紅麴", "葡萄糖胺", "魚油"}


def number(raw):
    raw = raw.replace(",", "").strip()
    value = float(raw)
    return int(value) if value.is_integer() else value


def parse_value(raw):
    raw = raw.strip()
    if raw == "—":
        return None
    if raw.startswith("<"):
        return {"operator": "<", "value": number(raw[1:])}
    if "–" in raw:
        lower, upper = raw.split("–", 1)
        return {"min": number(lower), "max": number(upper)}
    return number(raw)


def parse_age_cells(cells):
    result = {}
    for band, cell in zip(AGE_BANDS, cells, strict=True):
        if cell == "—":
            result[band] = {"male": None, "female": None}
            continue
        values = cell.split("／")
        if len(values) != 2:
            raise ValueError(f"預期男／女兩個值：{cell}")
        result[band] = {"male": parse_value(values[0]), "female": parse_value(values[1])}
    return result


def literal_assignment(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"營養品評估.py 找不到 {name}")


tree = ast.parse((SOURCE_DIR / "營養品評估.py").read_text(encoding="utf-8-sig"))
products = literal_assignment(tree, "PRODUCTS")
ul = literal_assignment(tree, "UL")
expected_keys = set(products[0]["nutrients"])
if expected_keys != set(ENGLISH):
    raise ValueError(f"中英名稱與 PRODUCTS 鍵不一致：{expected_keys ^ set(ENGLISH)}")

nutrients = OrderedDict()
for name in products[0]["nutrients"]:
    en, aliases = ENGLISH[name]
    nutrients[name] = {
        "name_zh": name,
        "name_en": en,
        "aliases_en": aliases,
        "input_unit": "mg" if name in EXTRAS else None,
        "daily_references": [],
        "upper_limit": None,
    }

table = None
for line in (SOURCE_DIR / "md資料" / "規則.md").read_text(encoding="utf-8-sig").splitlines():
    if line.startswith("| 營養素（單位）"):
        table = "main"
        continue
    if line.startswith("| 膳食纖維（g；活動強度）"):
        table = "fiber"
        continue
    if table is None or not line.startswith("|"):
        continue
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cells) != 5 or cells[0].startswith("-"):
        continue
    if table == "main":
        match = re.fullmatch(r"(.+?)（(.+?)）", cells[0])
        if not match:
            raise ValueError(f"無法解析營養素表格列：{cells[0]}")
        label, unit = match.groups()
        name = re.sub(r" (EAR|RDA|AMDR|CDRR)$", "", label)
        if name not in nutrients:
            raise ValueError(f"規則.md 中的未知營養素：{name}")
        if nutrients[name]["input_unit"] is None:
            nutrients[name]["input_unit"] = "g" if unit == "總熱量 %" else unit
        nutrients[name]["daily_references"].append({
            "label_zh": label,
            "unit": unit,
            "by_age_and_sex": parse_age_cells(cells[1:]),
        })
    elif cells[0] in ("低", "稍低", "適度", "高"):
        nutrients["膳食纖維"]["daily_references"].append({
            "activity": cells[0],
            "unit": "g",
            "by_age_and_sex": parse_age_cells(cells[1:]),
        })
        nutrients["膳食纖維"]["input_unit"] = "g"

for name, limit in ul.items():
    if name not in nutrients:
        raise ValueError(f"UL 中的未知營養素：{name}")
    values = list(limit) if isinstance(limit, tuple) else [limit] * 4
    if len(values) == 2:  # 磷：19–70 歲／71 歲以上
        values = [values[0], values[0], values[0], values[1]]
    scope = "total_intake"
    if name == "鎂":
        scope = "non_food_sources"
    elif name == "鐵":
        scope = "fortified_food_and_supplements"
    nutrients[name]["upper_limit"] = {
        "unit": nutrients[name]["input_unit"],
        "scope": scope,
        "by_age_band": dict(zip(AGE_BANDS, values, strict=True)),
    }

if sum(len(n["daily_references"]) for n in nutrients.values()) != 37:
    raise ValueError("預期 33 筆主表數值及 4 筆膳食纖維數值")
if any(not n["daily_references"] for k, n in nutrients.items() if k not in EXTRAS):
    raise ValueError("有營養素缺少參考值")

database = {
    "schema_version": "1.0",
    "source": {
        "daily_references": "規則.md（依國人膳食營養素參考攝取量第八版總表）",
        "upper_limits": "營養品評估.py 中的 UL（依同一總表第 2 頁）",
        "official_url": "https://www.hpa.gov.tw/Pages/List.aspx?nodeid=4613",
    },
    "age_bands": [
        {"key": "19-30", "min_age": 19, "max_age": 30},
        {"key": "31-50", "min_age": 31, "max_age": 50},
        {"key": "51-70", "min_age": 51, "max_age": 70},
        {"key": "71+", "min_age": 71, "max_age": None},
    ],
    "nutrients": list(nutrients.values()),
}
path = OUTPUT_DIR / "營養素中英名稱與參考劑量.json"
path.write_text(json.dumps(database, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"{path}：{len(nutrients)} 個名稱，{sum(len(n['daily_references']) for n in nutrients.values())} 筆參考列")
