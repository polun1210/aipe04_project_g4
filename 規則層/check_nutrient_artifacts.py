import importlib.util
import json
from pathlib import Path

output_dir = Path(r"C:\Users\student\Documents\Codex\2026-10-04\new-chat\outputs")
database = json.loads((output_dir / "營養素中英名稱與參考劑量.json").read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("nutrient_names", output_dir / "營養素名稱中英轉換.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

assert len(database["nutrients"]) == 35
assert len({n["name_zh"] for n in database["nutrients"]}) == 35
for item in database["nutrients"]:
    assert module.name_to_zh(item["name_en"]) == item["name_zh"]
    assert module.name_to_en(item["name_zh"]) == item["name_en"]

by_zh = {item["name_zh"]: item for item in database["nutrients"]}
assert by_zh["維生素 D"]["daily_references"][0]["by_age_and_sex"]["51-70"]["female"] == 15
assert by_zh["鉀"]["daily_references"][0]["by_age_and_sex"]["71+"]["male"] == 2800
assert by_zh["磷"]["upper_limit"]["by_age_band"]["71+"] == 3000
assert by_zh["膳食纖維"]["daily_references"][3]["by_age_and_sex"]["71+"]["male"] is None

products = [{"name": "例子", "servings_per_day": 2, "nutrients": {"Vitamin C": [60, "mg"], "Vitamin D": [5, "µg"]}}]
translated = module.convert_product_nutrient_names(products)
assert translated[0]["nutrients"] == {"維生素 C": [60, "mg"], "維生素 D": [5, "µg"]}
assert products[0]["nutrients"] == {"Vitamin C": [60, "mg"], "Vitamin D": [5, "µg"]}

try:
    module.convert_product_nutrient_names([{"name": "例子", "nutrients": {"Vitamin C": [60, "mg"], "維生素 C": [10, "mg"]}}])
except ValueError:
    pass
else:
    raise AssertionError("中英文重複鍵應拒絕")

print("JSON 結構、35 個名稱雙向轉換、參考值與 PRODUCTS 格式檢查通過")
