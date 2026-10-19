"""評估：錄製的 VLM 結果 → extract() 產出的辨識草稿，與標準答案逐欄比對。不呼叫付費服務。

    uv run python scripts/eval_drafts.py [--engine openrouter] [--gold tests/fixtures/gold_w1]

比較集是可以拿來調規則的資料，所以這裡的數字偏樂觀；正式驗收要用沒調過規則的保留集。
逐欄正確 ＝ 範圍狀態、標準代碼、每份含量、單位都對（名稱、數值、單位都對才算對）。
"""

import argparse
import difflib
import re
import sys
import unicodedata
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.extraction import ImageInput, ReplayEngine, extract  # noqa: E402
from app.schemas.enums import QualityStatus  # noqa: E402
from app.schemas.label import ExtractionDraft, NutrientDraft, SourceImage  # noqa: E402

RECORDINGS = ROOT / "tests" / "fixtures" / "engine_responses"


def _k(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).lower()


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) < 1e-6


def _pair(draft_rows: list[NutrientDraft], gold_rows: list[NutrientDraft]):
    """依名稱配對：先完全相同，再取相似度最高且 ≥ 0.75 的。"""
    left = list(draft_rows)
    pairs, missing = [], []
    for g in gold_rows:
        exact = next((d for d in left if _k(d.raw_name) == _k(g.raw_name) and d.label_section == g.label_section), None)
        exact = exact or next((d for d in left if _k(d.raw_name) == _k(g.raw_name)), None)
        if exact is None:
            scored = [(difflib.SequenceMatcher(None, _k(d.raw_name), _k(g.raw_name)).ratio(), i) for i, d in enumerate(left)]
            best = max(scored, default=(0, None))
            exact = left[best[1]] if best[0] >= 0.75 else None
        if exact is None:
            missing.append(g)
        else:
            left.remove(exact)
            pairs.append((exact, g))
    return pairs, missing, left


def evaluate(engine_dir: str = "openrouter", gold_dir: Path = ROOT / "tests" / "fixtures" / "gold_w1") -> dict:
    totals = dict(gold=0, matched=0, missing=0, extra=0, full=0, scope=0, amount=0, unit=0, dv=0, section=0,
                  gold_in=0, in_found=0, in_full=0, draft_in=0, draft_in_wrong=0, serving=0, dose=0, images=0)
    problems: list[str] = []
    for gold_path in sorted(gold_dir.glob("p*.json")):
        gold = ExtractionDraft.model_validate_json(gold_path.read_text(encoding="utf-8"))
        image_id = gold.source_images[0].image_id
        draft = extract(
            UUID(int=1), [ImageInput(image_id=image_id, content=b"replay")],
            [SourceImage(image_id=image_id, quality_status=QualityStatus.ACCEPTED)],
            engine=ReplayEngine(RECORDINGS / engine_dir),
        )
        pairs, missing, extra = _pair(draft.nutrients, gold.nutrients)
        t = totals
        t["images"] += 1
        for key, n in (("gold", len(gold.nutrients)), ("matched", len(pairs)), ("missing", len(missing)), ("extra", len(extra))):
            t[key] += n
        t["serving"] += _same(draft.serving_info.serving_size, gold.serving_info.serving_size)
        t["dose"] += draft.serving_info.dose_unit == gold.serving_info.dose_unit
        for d, g in pairs:
            scope_ok = d.scope_status == g.scope_status and d.standard_code == g.standard_code
            ok = scope_ok and _same(d.per_serving, g.per_serving) and d.unit == g.unit
            checks = {
                "full": ok, "scope": scope_ok, "amount": _same(d.per_serving, g.per_serving), "unit": d.unit == g.unit,
                "dv": _same(d.percent_dv, g.percent_dv), "section": d.label_section == g.label_section,
            }
            for key, passed in checks.items():
                t[key] += passed
            if not ok:
                problems.append(f"{image_id} 「{g.raw_name}」 答案 {g.scope_status.value}/{g.standard_code}/{g.per_serving}{g.unit} "
                                f"→ 草稿 {d.scope_status.value}/{d.standard_code}/{d.per_serving}{d.unit}")
        gold_in = [g for g in gold.nutrients if g.scope_status.value == "in_scope"]
        t["gold_in"] += len(gold_in)
        for d, g in pairs:
            if g.scope_status.value == "in_scope" and d.scope_status.value == "in_scope" and d.standard_code == g.standard_code:
                t["in_found"] += 1
                t["in_full"] += _same(d.per_serving, g.per_serving) and d.unit == g.unit and d.nutrient_form_code == g.nutrient_form_code
        draft_in = [d for d in draft.nutrients if d.scope_status.value == "in_scope"]
        t["draft_in"] += len(draft_in)
        matched_in = {id(d) for d, g in pairs if g.scope_status.value == "in_scope" and d.standard_code == g.standard_code}
        t["draft_in_wrong"] += sum(1 for d in draft_in if id(d) not in matched_in)
        for g in missing:
            problems.append(f"{image_id} 漏抓「{g.raw_name}」（{g.scope_status.value}）")
        for d in extra:
            problems.append(f"{image_id} 多抓「{d.raw_name}」→ {d.scope_status.value}")
    totals["problems"] = problems
    return totals


def _pct(a: int, b: int) -> str:
    return f"{a}/{b}（{a / b:.0%}）" if b else "—"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser(description="辨識草稿對標準答案逐欄比對（錄製結果重播，不花錢）")
    parser.add_argument("--engine", default="openrouter", help="tests/fixtures/engine_responses/ 底下的引擎資料夾")
    parser.add_argument("--gold", type=Path, default=ROOT / "tests" / "fixtures" / "gold_w1", help="標準答案資料夾")
    args = parser.parse_args()
    t = evaluate(args.engine, args.gold)
    print(f"比較集 {t['images']} 張（可調規則的資料，數字偏樂觀）")
    print(f"- 逐欄正確（範圍、代碼、數值、單位都對）：{_pct(t['full'], t['gold'])}")
    print(f"- 漏抓：{_pct(t['missing'], t['gold'])}；多抓：{_pct(t['extra'], t['gold'])}")
    print(f"- 配對到的列：範圍狀態與代碼 {_pct(t['scope'], t['matched'])}、數值 {_pct(t['amount'], t['matched'])}、"
          f"單位 {_pct(t['unit'], t['matched'])}、%DV {_pct(t['dv'], t['matched'])}、區塊 {_pct(t['section'], t['matched'])}")
    print(f"- **範圍內成分**（真正進評估的）：找到 {_pct(t['in_found'], t['gold_in'])}，"
          f"其中數值、單位、型態全對 {_pct(t['in_full'], t['gold_in'])}；草稿多出的範圍內列 {t['draft_in_wrong']}")
    print(f"- 每一份量 {_pct(t['serving'], t['images'])}；劑型 {_pct(t['dose'], t['images'])}")
    print("\n錯誤明細：")
    for p in t["problems"]:
        print("  -", p)


if __name__ == "__main__":
    main()
