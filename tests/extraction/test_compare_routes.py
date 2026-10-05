"""兩方案小測比較表：用假的錄製結果與手寫的標準答案，從 build_report() 測輸出。"""

import json
from uuid import UUID

import pytest

from app.extraction.engines import cloud_vision, gemini
from scripts.compare_routes import build_report, main

PRODUCT = UUID("b2000000-0000-4000-8000-000000000002")


def gold_draft(nutrients: list[dict]) -> dict:
    return {
        "product_id": str(PRODUCT),
        "source_images": [{"image_id": "p01-img01", "quality_status": "accepted"}],
        "serving_info": {"serving_size": 2, "dose_unit": "capsule", "source_image_id": "p01-img01"},
        "nutrients": [
            {"row_id": f"r{i:02d}", "source_image_id": "p01-img01", **n} for i, n in enumerate(nutrients, start=1)
        ],
        "extraction_meta": {
            "ocr_version": "gold",
            "rule_layer_version": "gold",
            "synonym_table_version": "gold",
            "extracted_at": "2026-10-08T00:00:00Z",
        },
    }


VITAMIN_D = {"raw_name": "維生素D", "label_section": "nutrition_table", "standard_code": "vitamin_d",
             "scope_status": "in_scope", "per_serving": 10, "unit": "ug"}  # fmt: skip
CALCIUM = {"raw_name": "檸檬酸鈣(含純鈣50mg)", "label_section": "nutrition_table", "standard_code": "calcium",
           "scope_status": "in_scope", "per_serving": 238, "unit": "mg", "stated_elemental_amount": 50}  # fmt: skip
RED_YEAST = {"raw_name": "紅麴", "label_section": "ingredient_list", "standard_code": "red_yeast_rice",
             "scope_status": "in_scope"}  # fmt: skip
MAGNESIUM = {"raw_name": "鎂", "label_section": "nutrition_table", "standard_code": "magnesium",
             "scope_status": "in_scope", "per_serving": 100, "unit": "mg"}  # fmt: skip


@pytest.fixture
def responses(tmp_path, load_recording):
    """模擬 record_engines.py 對 p01-img01 錄好的兩個引擎結果；Cloud Vision 另有一張 p02-img01。"""
    root = tmp_path / "engine_responses"
    converters = {"cloud_vision": cloud_vision.to_engine_result, "gemini": gemini.to_engine_result}
    recordings = [("cloud_vision", "p01-img01"), ("cloud_vision", "p02-img01"), ("gemini", "p01-img01")]
    for engine, image_id in recordings:
        rec = load_recording(engine, "nutrition_table").model_copy(update={"image_id": image_id})
        (root / engine / "raw").mkdir(parents=True, exist_ok=True)
        (root / engine / "raw" / f"{image_id}.json").write_text(rec.model_dump_json(), encoding="utf-8")
        (root / engine / f"{image_id}.json").write_text(converters[engine](rec).model_dump_json(), encoding="utf-8")
    return root


def write_gold(tmp_path, nutrients):
    folder = tmp_path / "gold"
    folder.mkdir()
    (folder / "p01.json").write_text(json.dumps(gold_draft(nutrients), ensure_ascii=False), encoding="utf-8")
    return folder


def table_row(report: str, section: str, first_cell: str) -> list[str]:
    """取出某一節裡、第一格是 first_cell 的那一列表格。"""
    body = report.split(f"## {section}", 1)[1].split("\n## ", 1)[0]
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == first_cell:
            return cells[1:]
    raise AssertionError(f"{section} 裡找不到 {first_cell}")


# ── 沒有標準答案：只看引擎原始結果 ─────────────────────────────────


def test_每張圖列出兩個引擎的觀察值(responses):
    cells = table_row(build_report(responses), "每張圖", "p01-img01")
    # CV：4 行、含數值單位 1 行（10微克）、每一份量 2 粒、全部有框、812 ms
    # Gemini：3 列、每一份量 2 粒、3 列中 1 列有框、4321 ms
    assert cells == ["4", "1", "2 粒", "100%", "812", "3", "2 粒", "33%", "4321"]


def test_只有一個引擎錄到的照片標為未錄製(responses):
    cells = table_row(build_report(responses), "每張圖", "p02-img01")
    assert cells[5:] == ["未錄製"] * 4


def test_彙總讀到每一份量的張數(responses):
    assert table_row(build_report(responses), "彙總", "讀到每一份量") == ["2／2", "1／1"]


def test_彙總延遲中位數(responses):
    assert table_row(build_report(responses), "彙總", "延遲中位數 ms") == ["812", "4321"]


def test_沒給標準答案時不出現正確率(responses):
    assert "和標準答案比" not in build_report(responses)


# ── 有標準答案 ─────────────────────────────────────────────────────


def test_Gemini逐欄正確率以標準答案列數為分母(responses, tmp_path):
    # Gemini 讀到維生素D、檸檬酸鈣、紅麴三列都對；漏了鎂 → 3／4
    report = build_report(responses, write_gold(tmp_path, [VITAMIN_D, CALCIUM, RED_YEAST, MAGNESIUM]))
    assert table_row(report, "和標準答案比", "p01-img01")[1] == "75%（3／4）"
    assert table_row(report, "和標準答案比", "漏抓率")[0] == "25%（1／4）"


def test_單位原文對映後才和標準答案比較(responses, tmp_path):
    # Gemini 給「微克」，標準答案是 ug；若單位寫錯就不算對
    wrong_unit = dict(VITAMIN_D, unit="mg")
    report = build_report(responses, write_gold(tmp_path, [wrong_unit, CALCIUM, RED_YEAST]))
    assert table_row(report, "和標準答案比", "p01-img01")[1] == "67%（2／3）"


def test_數值讀錯的列不算對(responses, tmp_path):
    report = build_report(responses, write_gold(tmp_path, [dict(VITAMIN_D, per_serving=5), CALCIUM, RED_YEAST]))
    assert table_row(report, "和標準答案比", "p01-img01")[1] == "67%（2／3）"


def test_標準答案沒有的列算幻覺(responses, tmp_path):
    report = build_report(responses, write_gold(tmp_path, [VITAMIN_D, CALCIUM]))  # 紅麴不在答案裡
    assert table_row(report, "和標準答案比", "p01-img01")[2] == "33%（1／3）"


def test_每一份量和標準答案比對(responses, tmp_path):
    report = build_report(responses, write_gold(tmp_path, [VITAMIN_D]))
    cells = table_row(report, "和標準答案比", "p01-img01")
    assert (cells[3], cells[6]) == ("對", "對")


def test_CloudVision只算原文涵蓋率(responses, tmp_path):
    # CV 文字裡有「維生素D」與「10」；沒有檸檬酸鈣、紅麴、鎂的名稱，也沒有 238、100
    report = build_report(responses, write_gold(tmp_path, [VITAMIN_D, CALCIUM, RED_YEAST, MAGNESIUM]))
    cells = table_row(report, "和標準答案比", "p01-img01")
    assert (cells[4], cells[5]) == ("25%（1／4）", "33%（1／3）")


def test_寫到指定檔案(responses, tmp_path):
    out = tmp_path / "docs" / "route.md"
    assert main(["--responses", str(responses), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# 兩方案小測")
