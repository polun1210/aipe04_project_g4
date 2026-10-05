"""兩方案小測（W1）：比較 Cloud Vision 與 Gemini 錄好的結果，輸出 markdown 比較表。

    uv run python scripts/compare_routes.py --responses tests/fixtures/engine_responses \
        [--gold tests/fixtures/labels] [--out docs/w1/route-comparison.md]

W1 還沒有規則層，所以只比「引擎原始結果看得到的東西」：
- Cloud Vision 輸出的是文字行，還沒整理成成分列。「含數值單位的行」是「數字緊接單位」的行數，
  只是規則層可整理出幾列的粗略上限，不等於成分列數。
- Gemini 直接輸出成分列。
- 有標準答案時：Gemini 算逐欄正確率（名稱、數值、單位都對才算對，D05）、幻覺率、漏抓率；
  Cloud Vision 只算「標準答案的名稱與數值有沒有出現在讀到的文字裡」（涵蓋率），
  代表規則層最多能做到多好，不是正確率。兩者不可直接相比，表上分開列。
- 單位對映（毫克→mg 等）只為了這張表而寫，正式的單位對映屬於規則層（W2）。
"""

import argparse
import math
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 `python scripts/...` 找得到 app

from app.extraction.engines.base import EngineRecording, EngineResult, ReadingRow  # noqa: E402
from app.extraction.textnorm import compact, strip_parenthetical  # noqa: E402
from app.schemas.enums import Unit  # noqa: E402
from app.schemas.label import ExtractionDraft, NutrientDraft  # noqa: E402

ENGINES = ("cloud_vision", "gemini")
SERVING_KEYWORD = "每一份量"
_UNITS = r"(?:mg|毫克|μg|ug|mcg|微克|kcal|大卡|千卡|iu|國際單位|g|公克|克)"
_AMOUNT_WITH_UNIT = re.compile(r"\d+(?:\.\d+)?" + _UNITS, re.IGNORECASE)
_SERVING_VALUE = re.compile(SERVING_KEYWORD + r"[:：]?(\d+(?:\.\d+)?)([^\d(]{0,2})")  # 「每一份量2粒(1.2公克)」→ 2、粒
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# 只供本表使用的單位對映；比對前已做 NFKC（µ→μ）與去空白、轉小寫
_UNIT_MAP = {
    "mg": Unit.MG, "毫克": Unit.MG,
    "μg": Unit.UG, "ug": Unit.UG, "mcg": Unit.UG, "微克": Unit.UG,
    "g": Unit.G, "公克": Unit.G, "克": Unit.G,
    "kcal": Unit.KCAL, "大卡": Unit.KCAL, "千卡": Unit.KCAL,
    "iu": Unit.IU, "國際單位": Unit.IU,
    "mgα-te": Unit.MG_ATE, "mgne": Unit.MG_NE,
}  # fmt: skip


@dataclass
class Observation:
    """一張圖在一個引擎上看得到的東西。"""

    rows: int  # Gemini：成分列數；Cloud Vision：含數值單位的行數
    lines: int  # 文字區塊數
    serving: str  # 讀到的每一份量，或「有字無數值」「無」
    serving_found: bool
    bbox_ratio: float | None  # 有框的列（Gemini）或行（Cloud Vision）比例
    latency_ms: float | None


@dataclass
class GoldScore:
    gold_rows: int
    matched_rows: int | None = None  # Gemini：對得上標準答案某一列的列數（沒對上的就是漏抓）
    correct_rows: int | None = None  # Gemini：名稱、數值、單位都對的列數
    hallucinated: int | None = None  # Gemini：標準答案裡沒有的列數
    engine_rows: int | None = None
    name_hits: int | None = None  # Cloud Vision：名稱出現在文字裡的列數
    value_rows: int | None = None  # Cloud Vision：標準答案中有每份含量的列數
    value_hits: int | None = None  # Cloud Vision：其中數值出現在文字裡的列數
    serving_correct: bool | None = None  # 標準答案沒有每一份量時為 None


# ── 觀察值 ───────────────────────────────────────────────────────


def observe(result: EngineResult, latency_ms: float | None) -> Observation:
    if result.reading is not None:
        return _observe_reading(result, latency_ms)
    texts = [compact(b.text) for b in result.blocks]
    found, value, unit = _ocr_serving(texts)
    serving = "無" if not found else ("有字無數值" if value is None else f"{_fmt(value)} {unit}".strip())
    return Observation(
        rows=sum(bool(_AMOUNT_WITH_UNIT.search(t)) for t in texts),
        lines=len(texts),
        serving=serving,
        serving_found=found,
        bbox_ratio=_ratio(sum(b.bbox is not None for b in result.blocks), len(result.blocks)),
        latency_ms=latency_ms,
    )


def _ocr_serving(texts: list[str]) -> tuple[bool, float | None, str]:
    """OCR 文字行裡的「每一份量」：（有沒有這個字, 同一行緊接的數字, 數字後的字）。"""
    for text in texts:
        if SERVING_KEYWORD in text:
            match = _SERVING_VALUE.search(text)
            return (True, float(match.group(1)), match.group(2)) if match else (True, None, "")
    return False, None, ""


def _observe_reading(result: EngineResult, latency_ms: float | None) -> Observation:
    reading = result.reading
    serving = reading.serving
    if serving is None:
        text, found = "無", False
    elif serving.serving_size is None:
        text, found = "有字無數值", True
    else:
        text, found = f"{_fmt(serving.serving_size)} {serving.dose_unit_raw or ''}".strip(), True
    return Observation(
        rows=len(reading.rows),
        lines=len(result.blocks),
        serving=text,
        serving_found=found,
        bbox_ratio=_ratio(sum(r.bbox is not None for r in reading.rows), len(reading.rows)),
        latency_ms=latency_ms,
    )


# ── 和標準答案比 ─────────────────────────────────────────────────


def map_unit(raw: str | None) -> Unit | None:
    if raw is None:
        return None
    return _UNIT_MAP.get(compact(raw).lower(), Unit.OTHER)


def score(result: EngineResult, gold_rows: list[NutrientDraft], gold_serving: float | None) -> GoldScore:
    if result.reading is not None:
        return _score_reading(result, gold_rows, gold_serving)
    texts = [compact(b.text) for b in result.blocks]
    text = "\n".join(texts)  # 用換行接起來，名稱不會跨行湊出假的命中
    numbers = {float(n) for n in _NUMBER.findall(text)}
    with_value = [g for g in gold_rows if g.per_serving is not None]
    _, serving, _ = _ocr_serving(texts)
    return GoldScore(
        gold_rows=len(gold_rows),
        name_hits=sum(compact(g.raw_name) in text for g in gold_rows),
        value_rows=len(with_value),
        value_hits=sum(any(_same_number(g.per_serving, n) for n in numbers) for g in with_value),
        serving_correct=None if gold_serving is None else _same_number(serving, gold_serving),
    )


def _score_reading(result: EngineResult, gold_rows: list[NutrientDraft], gold_serving: float | None) -> GoldScore:
    remaining = list(result.reading.rows)
    matched = correct = 0
    for gold in gold_rows:
        match = _take_match(remaining, gold)
        if match is not None:
            matched += 1
            correct += _row_correct(match, gold)
    serving = result.reading.serving
    read = serving.serving_size if serving else None
    return GoldScore(
        gold_rows=len(gold_rows),
        matched_rows=matched,
        correct_rows=correct,
        hallucinated=len(remaining),  # 配對完還剩下的就是標準答案裡沒有的
        engine_rows=len(result.reading.rows),
        serving_correct=None if gold_serving is None else _same_number(read, gold_serving),
    )


def _take_match(rows: list[ReadingRow], gold: NutrientDraft) -> ReadingRow | None:
    """依「名稱去括號」找第一個對得上的列並從清單移除（同名多列依序一對一）。"""
    key = strip_parenthetical(gold.raw_name)
    for i, row in enumerate(rows):
        if strip_parenthetical(row.raw_name) == key:
            return rows.pop(i)
    return None


def _row_correct(row: ReadingRow, gold: NutrientDraft) -> bool:
    return (
        compact(row.raw_name) == compact(gold.raw_name)
        and _same_number(row.amount, gold.per_serving)
        and map_unit(row.unit_raw) == gold.unit
    )


def _same_number(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)


# ── 讀檔 ─────────────────────────────────────────────────────────


def load_engine(folder: Path) -> tuple[dict[str, EngineResult], dict[str, float]]:
    """讀 record_engines.py 的輸出：<folder>/<id>.json 與 <folder>/raw/<id>.json（延遲）。"""
    results: dict[str, EngineResult] = {}
    latency: dict[str, float] = {}
    if not folder.is_dir():
        return results, latency
    for path in sorted(folder.glob("*.json")):
        result = EngineResult.model_validate_json(path.read_text(encoding="utf-8"))
        results[result.image_id] = result
    for path in sorted((folder / "raw").glob("*.json")):
        recording = EngineRecording.model_validate_json(path.read_text(encoding="utf-8"))
        latency[recording.image_id] = recording.latency_ms
    return results, latency


def load_gold(folder: Path) -> tuple[dict[str, list[NutrientDraft]], dict[str, float | None]]:
    """標準答案以辨識草稿結構存放（spec「資料與標準答案」）；依 source_image_id 拆到每張圖。"""
    rows: dict[str, list[NutrientDraft]] = {}
    serving: dict[str, float | None] = {}
    for path in sorted(folder.glob("*.json")):
        draft = ExtractionDraft.model_validate_json(path.read_text(encoding="utf-8"))
        for src in draft.source_images:
            rows.setdefault(src.image_id, [])
        for row in draft.nutrients:
            rows.setdefault(row.source_image_id, []).append(row)
        if draft.serving_info.source_image_id is not None:
            serving[draft.serving_info.source_image_id] = draft.serving_info.serving_size
    return rows, serving


# ── 輸出 ─────────────────────────────────────────────────────────


def build_report(responses: Path, gold: Path | None = None) -> str:
    data = {engine: load_engine(responses / engine) for engine in ENGINES}
    images = sorted({image_id for results, _ in data.values() for image_id in results})
    obs = {
        engine: {i: observe(r, latency.get(i)) for i, r in results.items()}
        for engine, (results, latency) in data.items()
    }
    lines = [
        "# 兩方案小測：Cloud Vision vs Gemini（W1）",
        "",
        f"- 照片：{len(images)} 張；錄製資料：`{responses.as_posix()}`",
        "- 還沒有規則層，下表只比較引擎原始結果看得到的東西（說明見 scripts/compare_routes.py）",
        "",
        "## 每張圖",
        "",
        "| 照片 | CV 文字行 | CV 含數值單位的行 | CV 每一份量 | CV 有框比例 | CV 延遲 ms"
        " | Gemini 成分列 | Gemini 每一份量 | Gemini 有框比例 | Gemini 延遲 ms |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for image_id in images:
        cv, gm = obs["cloud_vision"].get(image_id), obs["gemini"].get(image_id)
        cells = [image_id]
        cells += [str(cv.lines), str(cv.rows), cv.serving, _pct(cv.bbox_ratio), _ms(cv.latency_ms)] if cv else ["未錄製"] * 5
        cells += [str(gm.rows), gm.serving, _pct(gm.bbox_ratio), _ms(gm.latency_ms)] if gm else ["未錄製"] * 4
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## 彙總", "", "| 項目 | Cloud Vision | Gemini |", "|---|---|---|"]
    summary = {engine: _summary(list(obs[engine].values())) for engine in ENGINES}
    for label in summary["cloud_vision"]:
        lines.append(f"| {label} | {summary['cloud_vision'][label]} | {summary['gemini'][label]} |")

    if gold is not None:
        lines += _gold_section(data, *load_gold(gold), images)
    return "\n".join(lines) + "\n"


def _summary(items: list[Observation]) -> dict[str, str]:
    latencies = [o.latency_ms for o in items if o.latency_ms is not None]
    ratios = [o.bbox_ratio for o in items if o.bbox_ratio is not None]
    return {
        "已錄製張數": str(len(items)),
        "讀到每一份量": f"{sum(o.serving_found for o in items)}／{len(items)}",
        "平均有框比例": _pct(statistics.mean(ratios) if ratios else None),
        "延遲中位數 ms": _ms(statistics.median(latencies) if latencies else None),
        "延遲最大值 ms": _ms(max(latencies) if latencies else None),
    }


def _gold_section(data, gold_rows, gold_serving, images) -> list[str]:
    lines = [
        "",
        "## 和標準答案比",
        "",
        "- Gemini 逐欄正確率＝名稱、數值、單位都對的列 ÷ 標準答案列數；幻覺率＝標準答案沒有的列 ÷ Gemini 列數。",
        "- 漏抓率＝標準答案裡 Gemini 完全沒讀到的列 ÷ 標準答案列數。",
        "- Cloud Vision 涵蓋率＝標準答案的名稱（或數值）出現在讀到的文字裡的比例，是規則層的上限，不是正確率。",
        "",
        "| 照片 | 標準答案列數 | Gemini 逐欄正確率 | Gemini 幻覺率 | Gemini 每一份量 | CV 名稱涵蓋率 | CV 數值涵蓋率 | CV 每一份量 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    totals = {e: [] for e in ENGINES}
    for image_id in images:
        if image_id not in gold_rows:
            continue
        rows, serving = gold_rows[image_id], gold_serving.get(image_id)
        cv_result, gm_result = data["cloud_vision"][0].get(image_id), data["gemini"][0].get(image_id)
        cv = score(cv_result, rows, serving) if cv_result else None
        gm = score(gm_result, rows, serving) if gm_result else None
        if cv:
            totals["cloud_vision"].append(cv)
        if gm:
            totals["gemini"].append(gm)
        cells = [image_id, str(len(rows))]
        cells += [_frac(gm.correct_rows, gm.gold_rows), _frac(gm.hallucinated, gm.engine_rows), _ok(gm.serving_correct)] if gm else ["未錄製"] * 3
        cells += [_frac(cv.name_hits, cv.gold_rows), _frac(cv.value_hits, cv.value_rows), _ok(cv.serving_correct)] if cv else ["未錄製"] * 3
        lines.append("| " + " | ".join(cells) + " |")

    gm, cv = totals["gemini"], totals["cloud_vision"]
    lines += [
        "",
        "| 合計 | Gemini | Cloud Vision |",
        "|---|---|---|",
        f"| 逐欄正確率 | {_frac(sum(s.correct_rows for s in gm), sum(s.gold_rows for s in gm))} | 規則層完成後才能算 |",
        f"| 漏抓率 | {_frac(sum(s.gold_rows - s.matched_rows for s in gm), sum(s.gold_rows for s in gm))} | — |",
        f"| 幻覺率 | {_frac(sum(s.hallucinated for s in gm), sum(s.engine_rows for s in gm))} | — |",
        f"| 名稱涵蓋率 | — | {_frac(sum(s.name_hits for s in cv), sum(s.gold_rows for s in cv))} |",
        f"| 數值涵蓋率 | — | {_frac(sum(s.value_hits for s in cv), sum(s.value_rows for s in cv))} |",
        f"| 每一份量正確 | {_count_ok(gm)} | {_count_ok(cv)} |",
    ]
    return lines


def _count_ok(scores: list[GoldScore]) -> str:
    judged = [s.serving_correct for s in scores if s.serving_correct is not None]
    return f"{sum(judged)}／{len(judged)}" if judged else "—"


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _frac(part: int | None, whole: int | None) -> str:
    if part is None or not whole:
        return "—"
    return f"{part / whole:.0%}（{part}／{whole}）"


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def _ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}"


def _ok(value: bool | None) -> str:
    return "—" if value is None else ("對" if value else "錯")


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="兩方案小測比較表（只讀錄好的結果，不呼叫服務）")
    parser.add_argument("--responses", type=Path, default=Path("tests/fixtures/engine_responses"))
    parser.add_argument("--gold", type=Path, help="標準答案資料夾（辨識草稿結構的 JSON）")
    parser.add_argument("--out", type=Path, help="寫到檔案；不給就印在畫面上")
    args = parser.parse_args(argv)
    report = build_report(args.responses, args.gold)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"已寫出 {args.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
