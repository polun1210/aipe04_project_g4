"""將營養品評估.py 的 PRODUCTS[*]['nutrients'] 鍵在中文與英文之間轉換。"""

import json
import re
import unicodedata
from pathlib import Path


JSON_PATH = Path(__file__).with_name("營養素中英名稱與參考劑量.json")


def normalize_name(name):
    """比對時忽略大小寫、空格、連字號與底線。"""
    text = unicodedata.normalize("NFKC", str(name)).casefold().strip()
    return re.sub(r"[\s_-]+", "", text)


def load_name_maps():
    database = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    to_zh = {}
    to_en = {}

    for item in database["nutrients"]:
        zh = item["name_zh"]  # 與營養品評估.py 的 PRODUCTS 鍵完全相同
        en = item["name_en"]
        to_en[normalize_name(zh)] = en

        # 英文正式名稱、別名，以及原本的中文名稱都可轉成中文鍵。
        for candidate in [en, *item.get("aliases_en", []), zh]:
            key = normalize_name(candidate)
            if key in to_zh and to_zh[key] != zh:
                raise ValueError(f"名稱重複對應到不同營養素：{candidate}")
            to_zh[key] = zh

    return to_zh, to_en


TO_ZH, TO_EN = load_name_maps()


def name_to_zh(name):
    """例如 Vitamin C → 維生素 C。"""
    key = normalize_name(name)
    if key not in TO_ZH:
        raise ValueError(f"資料庫中沒有這個營養素名稱：{name}")
    return TO_ZH[key]


def name_to_en(name):
    """例如 維生素 C → Vitamin C。"""
    zh = name_to_zh(name)
    return TO_EN[normalize_name(zh)]


def convert_product_nutrient_names(products, target="zh"):
    """轉換營養品評估.py 的 PRODUCTS 格式；含量與單位原封不動。"""
    if target not in ("zh", "en"):
        raise ValueError('target 只能是 "zh" 或 "en"')

    convert = name_to_zh if target == "zh" else name_to_en
    converted_products = []

    for product in products:
        converted_nutrients = {}
        for original_name, dose in product["nutrients"].items():
            new_name = convert(original_name)
            if new_name in converted_nutrients:
                raise ValueError(f"產品 {product['name']} 有重複的營養素：{new_name}")
            converted_nutrients[new_name] = dose

        converted_products.append({
            **product,
            "nutrients": converted_nutrients,
        })

    return converted_products


if __name__ == "__main__":
    # 範例格式與營養品評估.py 的 PRODUCTS 相同。
    products_en = [
        {
            "name": "測試保健品",
            "servings_per_day": 2,
            "nutrients": {
                "Vitamin C": (60, "mg"),
                "Vitamin B12": (1.2, "µg"),
                "Calcium": (250, "mg"),
                "Potassium": (100, "mg"),
            },
        }
    ]

    products_zh = convert_product_nutrient_names(products_en, target="zh")
    print(products_zh)
    print(name_to_en("維生素 C"))
