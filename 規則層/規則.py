from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import unicodedata


# ==============================================================
# 1. 測試輸入區：日後改參數，只需改這裡
# ==============================================================
try:
    BASE_DIR = Path(__file__).resolve().parent  # 執行 .py：程式檔所在資料夾
except NameError:
    BASE_DIR = Path.cwd()  # Jupyter Notebook 沒有 __file__

if (BASE_DIR / "規則.md").is_file():
    RULE_DIR = BASE_DIR  # 規則.py 本身就在「規則層」內
else:
    RULE_DIR = BASE_DIR / "規則層"  # 程式在專案根目錄時
if not (RULE_DIR / "規則.md").is_file() and (BASE_DIR / "outputs" / "規則層" / "規則.md").is_file():
    RULE_DIR = BASE_DIR / "outputs" / "規則層"
REFERENCE_MD = RULE_DIR / "規則.md"                 # 成人每日參考值
INTERACTION_MD = RULE_DIR / "交互作用規則(複查)(覆蓋型更新).md"  # 用藥規則
PDF_SOURCE = RULE_DIR / "「國人膳食營養素參考攝取量」第八版_總表(1111020) (1).pdf"  # 人工核對來源；執行時不解析 PDF

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

# 某些藥品也提供元素鈣／鎂。只在使用對應藥品時填；留空會顯示「總量未能計算」。
MEDICATION_ELEMENTAL_PER_DAY = {
    "Calcium carbonate": {"鈣": None},       # 例如 (500, "mg")
    "Magnesium hydroxide": {"鎂": None},    # 例如 (100, "mg")
    "Magnesium oxide": {"鎂": None},        # 例如 (100, "mg")
    "鋁鎂複方": {"鎂": None},                 # 元素鎂，不是化合物重量
}

# 交互作用需要的補充條件：None = 未確認；True／False = 已確認是／否。
CONTEXT = {
    "long_term_use": {},              # 例：{"Omeprazole": True}；PPI／H2RA 長期使用
    "iron_deficiency_or_poor_response": None,  # 已缺鐵或補鐵反應不佳
    "nonheme_iron_supplement": None,  # 鐵產品是否為非血基質鐵
    "niacin_form": None,             # "nicotinic acid" 或 "nicotinamide"
    "niacin_for_lipids": None,       # 是否作降血脂用途
    "nicotinic_acid_mg_per_day": None,  # 僅判交互作用；一般用量仍須填 PRODUCTS 的菸鹼素，勿重複計入
    "high_dose_nicotinic_acid": None,  # 血糖規則是否已確認屬高劑量
    "pravastatin_niacin_dose_confirmed": None,  # 仿單條件已核對
    "monacolin_k_present": None,     # 紅麴產品是否確定含 monacolin K
    "al_mg_antacid_same_time": None, # Rosuvastatin 與鋁鎂複方制酸劑是否同時用
    "calcium_carbonate_with_iron": None,  # 碳酸鈣和鐵是否同服
    "al_mg_product_iron_warning": None,  # 實際鋁鎂複方產品仿單是否有鐵警示
    "magmitt_product_verified": None,     # 氧化鎂是否為報告所列 Magmitt 產品
    "cimetidine_high_dose_with_antacid": None,  # 特定高劑量／合併制酸劑情境
}


# ==============================================================
# 2. 固定規則：已依原始 PDF 第 2 頁成人 UL 表人工核對
# ==============================================================
# 數值是每日上限，單位與上方輸入一致。沒有列 UL 的營養素不要自行補值。
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
EXCLUDED_FIRST_VERSION = {
    ("Hydrochlorothiazide", "維生素 D"),
    ("Indapamide", "維生素 D"),
    ("Empagliflozin", "菸鹼素"),
    ("Dapagliflozin", "菸鹼素"),
}

# 只列報告中第一版可啟用且可寫成明確條件的高／中提示。
# 值是觸發條件名稱；報告原文、提示級別及行號會在執行時讀取原檔。
RULE_MODES = {
    "Hydrochlorothiazide": {"鈣": "supplement", "鉀": "medicine", "鎂": "medicine", "鋅": "medicine"},
    "Indapamide": {"鈣": "supplement", "鉀": "medicine", "鎂": "medicine"},
    "Losartan": {"鉀": "supplement"},
    "Valsartan": {"鉀": "supplement"},
    "Irbesartan": {"鉀": "supplement"},
    "Telmisartan": {"鉀": "supplement"},
    "Lisinopril": {"鉀": "supplement"},
    "Metformin": {"維生素 B12": "medicine", "菸鹼素": "niacin_glycemic"},
    "胰島素": {"鉀": "medicine", "菸鹼素": "niacin_glycemic"},
    "Atorvastatin": {"紅麴": "red_yeast", "菸鹼素": "niacin_statin"},
    "Rosuvastatin": {"紅麴": "red_yeast", "菸鹼素": "niacin_statin", "鎂": "al_mg_antacid"},
    "Simvastatin": {"紅麴": "red_yeast", "菸鹼素": "niacin_statin"},
    "Pravastatin": {"紅麴": "red_yeast", "菸鹼素": "pravastatin_niacin"},
    "Omeprazole": {"鎂": "long_term", "維生素 B12": "medicine", "鐵": "ppi_iron"},
    "Esomeprazole": {"鎂": "long_term", "維生素 B12": "medicine", "鐵": "ppi_iron"},
    "Lansoprazole": {"鎂": "long_term", "維生素 B12": "medicine", "鐵": "ppi_iron"},
    "Pantoprazole": {"鎂": "long_term", "維生素 B12": "medicine", "鐵": "ppi_iron"},
    "Rabeprazole": {"鎂": "long_term", "維生素 B12": "medicine", "鐵": "ppi_iron"},
    "Famotidine": {"維生素 B12": "medicine", "鐵": "long_term"},
    "Cimetidine": {"維生素 B12": "medicine", "鐵": "cimetidine_iron"},
    "Nizatidine": {"維生素 B12": "medicine", "鐵": "long_term"},
    "Calcium carbonate": {"鐵": "calcium_iron"},
    "鋁鎂複方": {"鐵": "al_mg_iron"},
    "Magnesium oxide": {"鐵": "magmitt_iron"},
}

MED_ALIASES = {
    "氯沙坦": "Losartan", "二甲雙胍": "Metformin", "insulin": "胰島素",
    "hctz": "Hydrochlorothiazide", "碳酸鈣": "Calcium carbonate",
    "氫氧化鎂": "Magnesium hydroxide", "氧化鎂": "Magnesium oxide",
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


def canonical_med(name, known):
    key = str(name).strip().casefold()
    aliases = {k.casefold(): v for k, v in MED_ALIASES.items()}
    if key in aliases:
        return aliases[key]
    return next((item for item in known if item.casefold() == key), str(name).strip())


def base_nutrient(label):
    label = re.sub(r"〔.*?〕", "", label).strip()
    return re.sub(r" (EAR|RDA|AMDR|CDRR)$", "", label)


def parse_reference():
    text = REFERENCE_MD.read_text(encoding="utf-8-sig")
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


def parse_interactions():
    text = INTERACTION_MD.read_text(encoding="utf-8-sig")
    section, rules = None, {}
    for line_no, line in enumerate(text.splitlines(), 1):
        found = re.match(r"^## ([2-7])\. ", line)
        if found:
            section = int(found.group(1))
            continue
        if line.startswith("## 8."):
            section = None
        if section is None or not line.startswith("|"):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(cells) != 8 or cells[0] in ("藥物成分", "---"):
            continue
        med, severity, nutrient = cells[:3]
        key = (med, base_nutrient(nutrient))
        if key in rules:
            raise ValueError(f"交互作用規則重複：{key}")
        rules[key] = {"severity": severity, "message": cells[5].replace("**", ""), "line": line_no}
    if len(rules) != 88:
        raise ValueError(f"預期讀到 88 筆詳細規則，實際為 {len(rules)} 筆；請檢查原檔")
    active = {(med, nutrient) for med, mapping in RULE_MODES.items() for nutrient in mapping}
    eligible = {
        key for key, rule in rules.items()
        if rule["severity"].startswith(("高", "中"))
        and "第一版不啟用" not in rule["severity"]
        and key not in EXCLUDED_FIRST_VERSION
    }
    if active != eligible:
        raise ValueError(f"啟用規則與報告不一致；缺少={sorted(eligible-active)}；多出={sorted(active-eligible)}")
    return rules


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


def normalize_inputs(units, medications):
    """第一階段：把每份產品及含元素的藥品都換成參考表單位。"""
    normalized_products = []
    for product in PRODUCTS:
        servings = dec(product["servings_per_day"], f"{product['name']} 每日份數")
        entries = product["nutrients"]
        extras = set(entries) - set(units)
        if extras:
            raise ValueError(f"{product['name']} 有未知營養素：{sorted(extras)}")
        converted = {}
        if servings > 0:
            for name, wanted in units.items():
                converted[name] = convert_amount(entries.get(name), wanted, f"{product['name']}／{name}")
        normalized_products.append((product["name"], servings, converted))
    normalized_medicines = {}
    for med, nutrients in MEDICATION_ELEMENTAL_PER_DAY.items():
        if med in medications:
            normalized_medicines[med] = {
                name: convert_amount(entry, units[name], f"{med}／元素{name}")
                for name, entry in nutrients.items()
            }
    return normalized_products, normalized_medicines


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


def positive_or_unknown(name, totals, unknown):
    if totals.get(name, 0) > 0:
        return "hit"
    return "confirm" if name in unknown else "no"


def trigger(med, nutrient, mode, totals, unknown):
    present = positive_or_unknown(nutrient, totals, unknown)
    if mode == "medicine":
        return "hit"
    if mode == "supplement":
        return present
    if mode == "long_term":
        value = CONTEXT["long_term_use"].get(med)
        return "hit" if value is True else "no" if value is False else "confirm"
    if mode == "ppi_iron":
        if CONTEXT["iron_deficiency_or_poor_response"] is True:
            return "hit"
        if CONTEXT["nonheme_iron_supplement"] is True and present == "hit":
            return "hit"
        return "confirm" if present != "no" else "no"
    if mode == "niacin_glycemic":
        if CONTEXT["niacin_form"] == "nicotinamide":
            return "no"
        dose = CONTEXT["nicotinic_acid_mg_per_day"]
        if CONTEXT["niacin_form"] == "nicotinic acid" and dose is not None and dec(dose, "菸鹼酸每日量") > 0:
            flag = CONTEXT["high_dose_nicotinic_acid"]
            return "hit" if flag is True else "no" if flag is False else "confirm"
        return "confirm" if present != "no" else "no"
    if mode in ("niacin_statin", "pravastatin_niacin"):
        if CONTEXT["niacin_form"] == "nicotinamide" or CONTEXT["niacin_for_lipids"] is False:
            return "no"
        dose = CONTEXT["nicotinic_acid_mg_per_day"]
        if CONTEXT["niacin_form"] != "nicotinic acid" or CONTEXT["niacin_for_lipids"] is not True or dose is None:
            return "confirm" if present != "no" else "no"
        dose = dec(dose, "菸鹼酸每日量")
        if mode == "pravastatin_niacin":
            flag = CONTEXT["pravastatin_niacin_dose_confirmed"]
            return "hit" if dose > 0 and flag is True else "confirm" if dose > 0 and flag is None else "no"
        return "hit" if dose >= 1000 else "no"
    if mode == "red_yeast":
        if present == "no":
            return "no"
        flag = CONTEXT["monacolin_k_present"]
        return "hit" if flag is True and present == "hit" else "no" if flag is False else "confirm"
    field = {
        "al_mg_antacid": "al_mg_antacid_same_time",
        "calcium_iron": "calcium_carbonate_with_iron",
        "al_mg_iron": "al_mg_product_iron_warning",
        "magmitt_iron": "magmitt_product_verified",
        "cimetidine_iron": "cimetidine_high_dose_with_antacid",
    }.get(mode)
    if field is None:
        raise ValueError(f"尚未設定觸發方式：{mode}")
    if mode != "al_mg_antacid" and present == "no":
        return "no"
    flag = CONTEXT[field]
    if flag is False:
        return "no"
    if flag is True and (mode == "al_mg_antacid" or present == "hit"):
        return "hit"
    return "confirm"


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


def append_risk(lines, label, nutrient, hits):
    lines.append(f"\n{label}：【交互作用提示；跳過劑量評估】")
    for med, rule in sorted(hits[nutrient], key=lambda x: 0 if x[1]["severity"].startswith("高") else 1):
        level = "高" if rule["severity"].startswith("高") else "中"
        lines.append(f"  【{level}】{med} × {nutrient}：{rule['message']}（規則來源第 {rule['line']} 行）")


def make_report():
    age_index = age_group()
    if ACTIVITY not in ("低", "稍低", "適度", "高") or (AGE >= 71 and ACTIVITY == "高"):
        raise ValueError("活動強度未列於此年齡層的規則表")
    missing = [str(path) for path in (REFERENCE_MD, INTERACTION_MD, PDF_SOURCE) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"找不到規則檔：{missing}。目前工作目錄是 {Path.cwd()}；"
            "請把『規則層』放在 .py 或 Notebook 所在資料夾，或修改 RULE_DIR。"
        )
    reference_rows, fiber = parse_reference()
    source_rules = parse_interactions()
    units = expected_units(reference_rows)
    known_meds = set(RULE_MODES) | set(MEDICATION_ELEMENTAL_PER_DAY)
    meds = {canonical_med(m, known_meds) for m in MEDICATIONS}
    normalized_products, normalized_medicines = normalize_inputs(units, meds)
    totals, unknown = aggregate(units, normalized_products, normalized_medicines)
    hits, pending = {}, []
    for med in sorted(meds):
        for nutrient, mode in RULE_MODES.get(med, {}).items():
            status = trigger(med, nutrient, mode, totals, unknown)
            rule = source_rules[(med, nutrient)]
            item = (med, rule)
            if status == "hit":
                hits.setdefault(nutrient, []).append(item)
            elif status == "confirm":
                pending.append((nutrient, med, rule["line"]))

    lines = [f"=== 成人保健品與用藥評估（{AGE} 歲、{SEX}） ==="]
    for label, unit, cells in reference_rows:
        nutrient = base_nutrient(label)
        if nutrient in hits:
            append_risk(lines, label, nutrient, hits)
            continue
        if nutrient in unknown:
            status = "部分含量已知，總量未能計算" if totals[nutrient] > 0 else "未記錄到相關營養素（不代表未攝取）"
            lines.append(f"\n{label}：{status}")
            continue
        if totals[nutrient] == 0:
            lines.append(f"\n{label}：已確認未攝取")
            continue
        lines.append(f"\n{label}：{describe_reference(label, unit, cells[age_index], totals[nutrient])}")
        limit = UL.get(nutrient)
        if isinstance(limit, tuple):
            limit = limit[0] if age_index < 3 else limit[1]
        if limit is not None:
            daily_limit = Decimal(limit)
            if totals[nutrient] >= daily_limit:
                word = "超過" if totals[nutrient] > daily_limit else "達到"
                lines.append(f"  警示：僅已輸入來源就{word} UL {number(daily_limit)} {units[nutrient]}。")
    fiber_target = dec(selected_reference(fiber[ACTIVITY][age_index]), "膳食纖維參考值")
    if "膳食纖維" in unknown:
        status = "部分含量已知，總量未能計算" if totals["膳食纖維"] > 0 else "未記錄到相關營養素（不代表未攝取）"
        lines.append(f"\n膳食纖維：{status}；{ACTIVITY}活動量參考 {number(fiber_target)} g／日。")
    elif totals["膳食纖維"] == 0:
        lines.append(f"\n膳食纖維：已確認未攝取；{ACTIVITY}活動量參考 {number(fiber_target)} g／日。")
    else:
        lines.append(f"\n膳食纖維：保健品提供 {number(totals['膳食纖維'])} g；相當於{ACTIVITY}活動量參考 {number(fiber_target)} g 的 {totals['膳食纖維'] / fiber_target * 100:.1f}%（僅保健品供給）。")

    for ingredient in ("紅麴", "葡萄糖胺", "魚油"):
        if ingredient in hits:
            append_risk(lines, ingredient, ingredient, hits)
        elif ingredient in unknown:
            lines.append(f"\n{ingredient}：未記錄到含量；原始營養素總表未列每日參考值。")
        elif totals[ingredient] == 0:
            lines.append(f"\n{ingredient}：已確認未攝取。")
        else:
            lines.append(f"\n{ingredient}：已輸入 {number(totals[ingredient])} mg／日；原始營養素總表未列每日參考值。")

    lines.append("\n=== 其他需確認事項 ===")
    if pending:
        lines.extend(f"{nutrient} × {med}：條件未確認，暫不判為高／中風險（規則來源第 {line} 行）。" for nutrient, med, line in pending)
    else:
        lines.append("無待確認的已列條件。")
    unknown_meds = sorted(meds - known_meds)
    if unknown_meds:
        lines.append(f"未納入本版規則的藥名：{', '.join(unknown_meds)}；不能解讀為沒有交互作用。")
    for med in ("Empagliflozin", "Dapagliflozin"):
        if med in meds and positive_or_unknown("鎂", totals, unknown) == "hit":
            lines.append(f"{med} × 鎂：報告僅允許資訊提示，不列高／中風險，也不跳過鎂的劑量評估。")
    lines.append("高／中為規則提示優先級；本程式沒有『低風險』或『安全』的自動判定。")
    lines.append("RDA／AI 與 UL 以全天來源理解；未輸入的一般飲食及藥品含量不視為 0。")
    return "\n".join(lines)


if __name__ == "__main__":
    print(make_report())  # 全部檢查完畢後，最後一次輸出報告
