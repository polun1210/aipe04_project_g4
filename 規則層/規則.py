"""整合營養品劑量評估與藥名辨識，並保存藥品辨識結果。

營養品輸入：營養品評估.py 的 AGE、SEX、ACTIVITY、PRODUCTS。
藥物輸入：藥物交互評估.py 的 MEDICATIONS。
"""

from pathlib import Path

from 營養品評估 import (
    AGE, SEX, ACTIVITY, PRODUCTS,
    aggregate, age_group, assess_extra_ingredient, assess_fiber,
    assess_nutrient, base_nutrient, expected_units, normalize_products,
    parse_reference,
)
from 藥物交互評估 import (
    MEDICATIONS, MEDICATION_OUTPUT_PATH, build_medication_output,
    format_medication_report, save_medication_output,
)

try:
    BASE_DIR = Path(__file__).resolve().parent  # 執行 .py：程式檔所在資料夾
except NameError:
    BASE_DIR = Path.cwd()  # Jupyter Notebook 沒有 __file__

MD_DIR = BASE_DIR / "md資料"  # Markdown 規則檔獨立存放於此；日後搬移時修改這一行
REFERENCE_MD = MD_DIR / "規則.md"  # 成人每日參考值
PDF_SOURCE = BASE_DIR / "「國人膳食營養素參考攝取量」第八版_總表(1111020) (1).pdf"  # 人工核對來源；執行時不解析 PDF

def make_report():
    age_index = age_group()
    if ACTIVITY not in ("低", "稍低", "適度", "高") or (AGE >= 71 and ACTIVITY == "高"):
        raise ValueError("活動強度未列於此年齡層的規則表")
    missing = [str(path) for path in (REFERENCE_MD, PDF_SOURCE) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"找不到資料檔：{missing}。目前工作目錄是 {Path.cwd()}；"
            "請檢查 MD_DIR 與 PDF_SOURCE 的路徑。"
        )
    reference_rows, fiber = parse_reference(REFERENCE_MD)
    units = expected_units(reference_rows)
    normalized_products = normalize_products(units, PRODUCTS)
    # 藥物目前只辨識名稱，因此營養素加總只計算保健品輸入。
    totals, unknown = aggregate(units, normalized_products, {})
    medication_output = build_medication_output(MEDICATIONS)
    # 後續查詢可使用 medication_output["query_names"]。
    # 查詢取得的資料預留在 medication_output["query_results"]，目前為 None。

    lines = [f"=== 成人保健品評估與藥名辨識（{AGE} 歲、{SEX}） ==="]
    for label, unit, cells in reference_rows:
        nutrient = base_nutrient(label)
        lines.extend(assess_nutrient(
            label, unit, cells[age_index], totals[nutrient],
            nutrient in unknown, age_index, units[nutrient],
        ))
    lines.append(assess_fiber(
        totals["膳食纖維"], "膳食纖維" in unknown,
        fiber[ACTIVITY][age_index], ACTIVITY,
    ))

    for ingredient in ("紅麴", "葡萄糖胺", "魚油"):
        lines.append(assess_extra_ingredient(
            ingredient, totals[ingredient], ingredient in unknown,
        ))

    lines.append("\n" + format_medication_report(medication_output["medications"]))
    lines.append("RDA／AI 與 UL 以全天來源理解；未輸入的一般飲食及藥品含量不視為 0。")
    save_medication_output(medication_output)
    return "\n".join(lines)

if __name__ == "__main__":
    print(make_report())
    print(f"\n藥品辨識結果已儲存：{MEDICATION_OUTPUT_PATH}")
