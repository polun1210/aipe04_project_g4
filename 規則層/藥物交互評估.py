"""依「藥品分支圖.md」建立的藥名辨識模組。

來源：C:/Users/student/Desktop/aipe04_project_g4/規則層/md資料/藥品分支圖.md
此檔內的名單是來源檔的副本；修改 Markdown 不會自動更新此檔。
本版辨識藥名與來源分組，沒有交互作用、劑量或風險等級判斷。
已接入「規則.py」；也可直接執行此檔，只輸出藥名辨識結果。
"""

import json
from pathlib import Path
import re
import unicodedata


# ==============================================================
# 1. 測試輸入區：把使用者輸入的藥名放進這個清單
# ==============================================================
# 支援英文大小寫、前後空白，以及分隔單字的多餘空白。
# 目前沒有收錄中文名與商品名；確認對應後可加入下方 MEDICATION_ALIASES。
MEDICATIONS = ["Losartan", "Metformin"]


# ==============================================================
# 2. 藥品名單：分組與藥名依照使用者提供的分支圖
# ==============================================================
# 新增品項：在對應分組的清單內增加一行 "藥品英文名稱", 即可。
# 分組僅表示來源檔的分類，不用來推斷使用者疾病。
MEDICATION_CATALOG = {
    "慢性關節炎": [
        "Etoricoxib",
        "Glucosamine hydrochloride",
        "Acetaminophen",
        "Celecoxib",
        "Glucosamine sulfate",
        # "未來新增的正式藥名",
    ],
    "腸胃用藥": [
        "Pantoprazole",
        "Rabeprazole",
        "Omeprazole",
        "Nizatidine",
        "Magnesium Oxide",
        "Cimetidine",
        "Famotidine",
        "Lansoprazole",
        "Calcium carbonate",
        "Magnesium hydroxide",
        "Esomeprazole",
        "Aluminum-Magnesium Compound",
        "aluminium hydroxide",
        # "未來新增的正式藥名",
    ],
    "慢性失眠症": [
        "Zolpidem",
        "Zopiclone",
        "Estazolam",
        "Melatonin",
        "Lorazepam",
        # "未來新增的正式藥名",
    ],
    "高血脂": [
        "Simvastatin",
        "Rosuvastatin",
        "Pravastatin",
        "Ezetimibe",
        "Atorvastatin",
        # "未來新增的正式藥名",
    ],
    # 新增分組時，可參考以下格式：
    # "新分組名稱": [
    #     "新藥品英文名稱",
    # ],
}


# 另有已確認的中文名、商品名或英文別名時，可在這裡增加對應。
# 右側必須填上方 MEDICATION_CATALOG 中的正式藥名。
MEDICATION_ALIASES = {
    # "已確認的中文名或商品名": "清單中的正式藥名",
}


# ==============================================================
# 3. 名稱比對：統一文字格式，再查詢完整藥名
# ==============================================================
def normalize_medication_name(name):
    """統一大小寫、全形字元、空白與單字間的連字號／底線。"""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("藥名必須是非空白的文字")
    text = unicodedata.normalize("NFKC", name).casefold().strip()
    return re.sub(r"[\s_-]+", " ", text)


def build_medication_index():
    """把名單整理成可以快速查詢的字典，並檢查名稱是否衝突。"""
    index = {}
    for category, names in MEDICATION_CATALOG.items():
        for name in names:
            key = normalize_medication_name(name)
            if key in index:
                raise ValueError(f"藥品名單重複或分組不明確：{name}")
            index[key] = {"medication_name": name, "category": category}

    # 先複製正式名稱索引，別名的右側只能指向正式藥名。
    official_names = dict(index)
    for alias, official_name in MEDICATION_ALIASES.items():
        official_key = normalize_medication_name(official_name)
        if official_key not in official_names:
            raise ValueError(f"別名 {alias} 對應的藥品不在名單內：{official_name}")
        alias_key = normalize_medication_name(alias)
        entry = official_names[official_key]
        if alias_key in index and index[alias_key] != entry:
            raise ValueError(f"別名對應到不同藥品：{alias}")
        index[alias_key] = entry
    return index


def identify_medications(medications):
    """逐一辨識使用者的藥名，回傳每筆結果；未辨識到的名稱也保留。"""
    if not isinstance(medications, (list, tuple)):
        raise ValueError('請使用藥名清單，例如 ["Omeprazole", "Zolpidem"]')

    index = build_medication_index()
    results = []
    for input_name in medications:
        key = normalize_medication_name(input_name)
        entry = index.get(key)
        results.append({
            "input_name": input_name,
            "matched": entry is not None,
            "medication_name": entry["medication_name"] if entry else None,
            "category": entry["category"] if entry else None,
        })
    return results


# ==============================================================
# 4. 輸出辨識報告：也可以直接使用 identify_medications() 的結果
# ==============================================================
def format_medication_report(results):
    """將辨識結果整理成顯示文字。"""
    lines = ["=== 藥品名稱辨識 ==="]
    if not results:
        lines.append("未輸入藥名。")
    for result in results:
        if result["matched"]:
            lines.append(
                f"{result['input_name']} → 已辨識：{result['medication_name']}"
                f"；分組：{result['category']}"
            )
        else:
            lines.append(f"{result['input_name']} → 未列入目前藥品名單。")
    lines.append("本結果只表示藥名是否列入名單，尚未進行交互作用或攝取風險評估。")
    return "\n".join(lines)



# ==============================================================
# 5. 後續查詢的輸出位置
# ==============================================================
# 執行本檔或「規則.py」時，將最新結果存成這個 JSON。
# 每次執行覆寫上一份結果；不是歷史紀錄檔。
MEDICATION_OUTPUT_PATH = Path(__file__).resolve().parent / "outputs" / "藥品辨識結果.json"


def build_medication_output(medications):
    """準備可供後續查詢使用的結構化資料。"""
    results = identify_medications(medications)
    # 只將已辨識的正式名稱放進待查詢清單，同一藥名只放一次。
    query_names = list(dict.fromkeys(
        item["medication_name"] for item in results if item["matched"]
    ))
    return {
        "schema_version": "1.0",
        "medications": results,
        "query_names": query_names,
        "unmatched_names": [
            item["input_name"] for item in results if not item["matched"]
        ],
        "query_results": None,  # 預留：未來查詢仿單或其他資料後，再填入結果
    }


def save_medication_output(output, output_path=None):
    """把辨識結果存成 JSON；需要另存檔時可指定 output_path。"""
    path = Path(output_path) if output_path is not None else MEDICATION_OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def make_report(medications):
    """僅回傳辨識報告文字；若需後續查詢資料，使用 build_medication_output。"""
    return format_medication_report(identify_medications(medications))


if __name__ == "__main__":
    medication_output = build_medication_output(MEDICATIONS)
    print(format_medication_report(medication_output["medications"]))
    saved_path = save_medication_output(medication_output)
    print(f"\n藥品辨識結果已儲存：{saved_path}")
