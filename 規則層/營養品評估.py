"""營養品：名稱、單位、每日攝取量與參考值判別。"""

from decimal import Decimal, InvalidOperation
import re
import unicodedata

from 營養素名稱中英轉換 import name_to_zh

# 修改營養品測試資料與成人條件，請看下方 AGE、SEX、PRODUCTS。
AGE = 35                    # 年齡：目前支援 19 歲以上
SEX = "男"                  # 性別："男" 或 "女"
ACTIVITY = "稍低"           # 膳食纖維參考值："低"、"稍低"、"適度"、"高"
DAILY_ENERGY_KCAL = None    # 可留空；有全天熱量時才比較「總熱量百分比」項目
MEDICATIONS = ["Losartan", "Metformin"]  # 藥物成分名；沒有用藥填 []

# 每份營養素含量：(數字, 單位)；None 或空字串表示未記錄，0 表示已確認未攝取。
# 一般重量可填 kg、g、mg、µg/ug/mcg、ng 及常見中文名稱；先換成參考表單位再計算。
# 維生素 A/E 與菸鹼素須保留 RE/α-TE/NE 型態，例如 (0.6, "mg RE")。
# IU 不是通用重量單位；這份依據未提供轉換規則，因此輸入 IU 會要求人工確認。
# 多款產品可在 PRODUCTS 中增列；每款各自設定每日份數。
PRODUCTS = [
    {
        "name": "綜合保健品",       # 產品名稱
        "servings_per_day": 2,  # 每天實際食用份數
        "nutrients": {
            "蛋白質": None,            # g
            "碳水化合物": None,        # g
            "膳食纖維": None,          # g
            "脂質": None,              # g
            "飽和脂肪酸": None,        # g
            "n-6 多元不飽和脂肪酸": None,  # g
            "n-3 多元不飽和脂肪酸": None,  # g
            "反式脂肪酸": None,        # g
            "維生素 A": None,          # µg RE；需有相同當量標示
            "維生素 D": (5, "µg"),      # µg
            "維生素 E": None,          # mg α-TE；需有相同當量標示
            "維生素 K": None,          # µg
            "維生素 C": (60, "mg"),     # mg
            "維生素 B1": None,         # mg
            "維生素 B2": None,         # mg
            "菸鹼素": None,            # mg NE；交互作用另須確認型態
            "維生素 B6": None,         # mg
            "維生素 B12": (1.2, "µg"),  # µg
            "葉酸": None,              # µg
            "膽素": None,              # mg
            "生物素": None,            # µg
            "泛酸": None,              # mg
            "鈣": (250, "mg"),         # mg，必須是元素鈣
            "磷": None,                # mg
            "鎂": None,                # mg，必須是元素鎂
            "鐵": None,                # mg，必須是元素鐵
            "鋅": None,                # mg
            "碘": None,                # µg
            "硒": None,                # µg
            "氟": None,                # mg
            "鈉": None,                # mg
            "鉀": (100, "mg"),         # mg
            "紅麴": None,              # mg；不是 DRIs 營養素
            "葡萄糖胺": None,          # mg；不是 DRIs 營養素
            "魚油": None,              # mg；不是 DRIs 營養素
        },
    },
]

UL = {
    "維生素 A": 3000, "維生素 D": 50, "維生素 E": 1000,
    "維生素 C": 2000, "維生素 B6": 80, "菸鹼素": 35,
    "葉酸": 1000, "膽素": 3500, "鈣": 2500,
    "磷": (4000, 3000),  # 19–70 歲／71 歲以上
    "鎂": 350,            # 僅非食物性鎂；本程式合計保健品與含鎂藥品
    "鐵": 40,             # 強化食品與補充劑等；本程式僅計已輸入的來源
    "鋅": 35, "碘": 1000, "硒": 400, "氟": 10,
}

PERCENT_ITEMS = {
    "碳水化合物 AMDR": ("碳水化合物", 4),
    "脂質": ("脂質", 9),
    "飽和脂肪酸": ("飽和脂肪酸", 9),
    "n-6 多元不飽和脂肪酸": ("n-6 多元不飽和脂肪酸", 9),
    "n-3 多元不飽和脂肪酸": ("n-3 多元不飽和脂肪酸", 9),
    "反式脂肪酸": ("反式脂肪酸", 9),
}

def dec(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} 必須是數字") from None
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} 必須是非負的有限數值")
    return result

def number(value):
    """將 Decimal 轉成容易閱讀的數字文字，不顯示換算留下的多餘零。"""
    result = format(Decimal(value), "f")
    return result.rstrip("0").rstrip(".") if "." in result else result

def age_group():
    if not isinstance(AGE, int) or AGE < 19:
        raise ValueError("目前只支援 19 歲以上成人")
    if SEX not in ("男", "女"):
        raise ValueError('SEX 請填 "男" 或 "女"')
    return 0 if AGE <= 30 else 1 if AGE <= 50 else 2 if AGE <= 70 else 3

def base_nutrient(label):
    label = re.sub(r"〔.*?〕", "", label).strip()
    return re.sub(r" (EAR|RDA|AMDR|CDRR)$", "", label)

def parse_reference(reference_md):
    text = reference_md.read_text(encoding="utf-8-sig")
    rows, fiber = [], {}
    current = None
    for line in text.splitlines():
        if line.startswith("| 營養素（單位）"):
            current = "main"
            continue
        if line.startswith("| 膳食纖維（g；活動強度）"):
            current = "fiber"
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0].startswith("-") or cells[0] == "":
            continue
        if current == "main":
            match = re.fullmatch(r"(.+?)（(.+?)）", cells[0])
            if not match:
                raise ValueError(f"無法解析參考值欄位：{cells[0]}")
            rows.append((match.group(1), match.group(2), cells[1:]))
        elif cells[0] in ("低", "稍低", "適度", "高"):
            fiber[cells[0]] = cells[1:]
    if len(rows) != 33 or len(fiber) != 4:
        raise ValueError("規則.md 表格格式或行數已改變，請先核對再執行")
    return rows, fiber

MASS_TO_MG = {
    "kg": Decimal("1000000"), "g": Decimal("1000"),
    "mg": Decimal("1"), "µg": Decimal("0.001"),
    "ng": Decimal("0.000001"),
}
MASS_ALIASES = {
    "kg": "kg", "公斤": "kg", "千克": "kg",
    "g": "g", "公克": "g", "克": "g", "gram": "g", "grams": "g",
    "mg": "mg", "毫克": "mg", "milligram": "mg", "milligrams": "mg",
    "µg": "µg", "ug": "µg", "mcg": "µg", "微克": "µg",
    "ng": "ng", "奈克": "ng", "納克": "ng", "nanogram": "ng", "nanograms": "ng",
}
EQUIVALENT_ALIASES = {"αte": "α-TE", "alphate": "α-TE", "re": "RE", "ne": "NE"}

def parse_unit(unit, field):
    """拆成重量單位與當量型態，例如 mg α-TE → (mg, α-TE)。"""
    raw = unicodedata.normalize("NFKC", str(unit)).strip().lower().replace("μ", "µ")
    raw = re.sub(r"[\s_-]", "", raw)
    if raw in ("iu", "國際單位"):
        raise ValueError(f"{field}：IU 無法通用換算；請先依營養素型態確認對應重量")
    for ending, equivalent in EQUIVALENT_ALIASES.items():
        if raw.endswith(ending) and raw[:-len(ending)] in MASS_ALIASES:
            return MASS_ALIASES[raw[:-len(ending)]], equivalent
    if raw in MASS_ALIASES:
        return MASS_ALIASES[raw], None
    raise ValueError(f"{field}：不支援的單位 {unit!r}")

def convert_amount(entry, wanted, field):
    if entry is None or entry == "":
        return None
    if not isinstance(entry, (tuple, list)) or len(entry) != 2:
        raise ValueError(f"{field} 應填 (數字, 單位)、None 或空字串")
    if entry[0] is None or entry[0] == "":
        return None
    amount = dec(entry[0], field)
    source_mass, source_equivalent = parse_unit(entry[1], field)
    target_mass, target_equivalent = parse_unit(wanted, f"{field} 參考單位")
    if source_equivalent != target_equivalent:
        raise ValueError(
            f"{field}：標示型態須為 {wanted}；RE、α-TE、NE 與一般重量不可直接互換"
        )
    return amount * MASS_TO_MG[source_mass] / MASS_TO_MG[target_mass]

def expected_units(reference_rows):
    units = {}
    for label, unit, _ in reference_rows:
        name = base_nutrient(label)
        units[name] = "g" if label in PERCENT_ITEMS else unit
    units.update({"膳食纖維": "g", "紅麴": "mg", "葡萄糖胺": "mg", "魚油": "mg"})
    return units

def normalize_products(units, products):
    """將產品營養素名稱統一成中文，再把每份含量換成參考表單位。"""
    normalized_products = []
    for product in products:
        servings = dec(product["servings_per_day"], f"{product['name']} 每日份數")
        entries = {}

        for input_name, dose in product["nutrients"].items():
            chinese_name = name_to_zh(input_name)
            if chinese_name in entries:
                raise ValueError(f"{product['name']} 重複輸入營養素：{chinese_name}")
            entries[chinese_name] = dose

        extras = set(entries) - set(units)
        if extras:
            raise ValueError(f"{product['name']} 有未知營養素：{sorted(extras)}")
        converted = {}
        if servings > 0:
            for name, wanted in units.items():
                converted[name] = convert_amount(entries.get(name), wanted, f"{product['name']}／{name}")
        normalized_products.append((product["name"], servings, converted))
    return normalized_products


def aggregate(units, normalized_products, normalized_medicines):
    """第二階段：只加總已轉為相同單位的數值。"""
    totals = {name: Decimal(0) for name in units}
    unknown = set()
    for _, servings, entries in normalized_products:
        if servings == 0:
            continue  # 已確認當天未食用該產品，空白標示不影響當日總量
        for name in units:
            value = entries[name]
            if value is None:
                unknown.add(name)
            else:
                totals[name] += value * servings
    for nutrients in normalized_medicines.values():
        for name, value in nutrients.items():
            if value is None:
                unknown.add(name)
            else:
                totals[name] += value
    return totals, unknown

def selected_reference(cell):
    value = cell.split("／")
    return value[0 if SEX == "男" else 1].strip() if len(value) == 2 else cell.strip()

def describe_reference(label, unit, cell, total):
    value = selected_reference(cell)
    if label in PERCENT_ITEMS:
        if DAILY_ENERGY_KCAL is None:
            return f"保健品提供 {number(total)} g；未填全天熱量，無法計算總熱量百分比（參考 {value}）。"
        kcal = dec(DAILY_ENERGY_KCAL, "全天熱量")
        if kcal == 0:
            raise ValueError("全天熱量須大於 0")
        pct = total * PERCENT_ITEMS[label][1] / kcal * 100
        return f"保健品提供 {number(total)} g，佔全天熱量 {pct:.1f}%（參考 {value}）。"
    target = dec(value.replace(",", ""), f"{label} 參考值")
    if target == 0:
        return "參考值為 0，無法計算比例。"
    ratio = total / target * 100
    if label == "鈉 CDRR":
        return f"保健品提供 {number(total)} {unit}；相當於 CDRR {number(target)} {unit} 的 {ratio:.1f}%（整天攝取仍需另計）。"
    return f"保健品提供 {number(total)} {unit}；相當於每日參考值 {number(target)} {unit} 的 {ratio:.1f}%（僅保健品供給）。"


def assess_nutrient(label, unit, cell, total, is_unknown, age_index, wanted_unit):
    """判別單一營養素的已知補充量、參考值比例及 UL。"""
    nutrient = base_nutrient(label)
    if is_unknown:
        status = "部分含量已知，總量未能計算" if total > 0 else "未記錄到相關營養素（不代表未攝取）"
        return [f"\n{label}：{status}"]
    if total == 0:
        return [f"\n{label}：已確認未攝取"]

    lines = [f"\n{label}：{describe_reference(label, unit, cell, total)}"]
    limit = UL.get(nutrient)
    if isinstance(limit, tuple):
        limit = limit[0] if age_index < 3 else limit[1]
    if limit is not None:
        daily_limit = Decimal(limit)
        if total >= daily_limit:
            word = "超過" if total > daily_limit else "達到"
            lines.append(f"  警示：僅已輸入來源就{word} UL {number(daily_limit)} {wanted_unit}。")
    return lines


def assess_fiber(total, is_unknown, target_cell, activity):
    """判別膳食纖維補充量。"""
    fiber_target = dec(selected_reference(target_cell), "膳食纖維參考值")
    if is_unknown:
        status = "部分含量已知，總量未能計算" if total > 0 else "未記錄到相關營養素（不代表未攝取）"
        return f"\n膳食纖維：{status}；{activity}活動量參考 {number(fiber_target)} g／日。"
    if total == 0:
        return f"\n膳食纖維：已確認未攝取；{activity}活動量參考 {number(fiber_target)} g／日。"
    return f"\n膳食纖維：保健品提供 {number(total)} g；相當於{activity}活動量參考 {number(fiber_target)} g 的 {total / fiber_target * 100:.1f}%（僅保健品供給）。"


def assess_extra_ingredient(ingredient, total, is_unknown):
    """顯示原始營養素總表未列參考值的保健品成分。"""
    if is_unknown:
        return f"\n{ingredient}：未記錄到含量；原始營養素總表未列每日參考值。"
    if total == 0:
        return f"\n{ingredient}：已確認未攝取。"
    return f"\n{ingredient}：已輸入 {number(total)} mg／日；原始營養素總表未列每日參考值。"

