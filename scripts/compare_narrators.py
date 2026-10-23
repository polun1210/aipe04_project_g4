"""LLM 敘述模型比較（W3 工單 7）：幾個模型 × 幾份評估結果 × 每份跑幾次，統計後寫成比較表。

    uv run python scripts/compare_narrators.py \
        --model google/gemini-3.8-flash@google-ai-studio --model 另一個型號@服務商 \
        [--case docs/schemas/examples/06_assessment.json ...] [--runs 3] [--out docs/w3/narrator-comparison]

會真的呼叫 OpenRouter（要花錢），金鑰讀 .env 的 OPENROUTER_API_KEY。
每次都照正式流程走：LLM 寫 → 輸出檢查 → 不合格重試，最多 2 次 → 仍不合格算「改用模板」。

輸出（--out 資料夾）：
- stats.md：每個模型一次就通過的比例、改用模板的比例、平均秒數、平均每份費用
- runs.jsonl：每一次呼叫的原始紀錄（文字、檢查結果、秒數、費用）
"""

import argparse
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 `python scripts/...` 找得到 app

from dotenv import load_dotenv  # noqa: E402

from app.catalog_source import get_catalog_source  # noqa: E402
from app.extraction.engines.openrouter import Route, Transport, http_transport  # noqa: E402
from app.narration_check import check_narration  # noqa: E402
from app.narrator import NarratorError, OpenRouterNarrator  # noqa: E402
from app.reporting import MAX_RETRIES  # noqa: E402
from app.schemas.assessment import Assessment  # noqa: E402
from app.schemas.narration import NarrationInput, NarrationOutput  # noqa: E402

DEFAULT_CASE = Path("docs/schemas/examples/06_assessment.json")


@dataclass
class Trial:
    """一個模型對一份評估跑一次（含重試）。"""

    model: str
    case: str
    run: int
    attempts: int = 0
    passed_first: bool = False
    fell_back: bool = True
    seconds: float = 0.0
    cost: float | None = None
    output: NarrationOutput | None = None
    violations: list[dict[str, Any]] = field(default_factory=list)


def metered(transport: Transport, log: list[dict[str, Any]]) -> Transport:
    """包一層記下每次呼叫的秒數與費用（OpenRouter 回應的 usage.cost，沒有就是 None）。"""

    def send(body: dict[str, Any], timeout: float) -> dict[str, Any]:
        started = perf_counter()
        response = transport(body, timeout)
        log.append({"seconds": perf_counter() - started, "cost": (response.get("usage") or {}).get("cost")})
        return response

    return send


def run_trial(narrator: OpenRouterNarrator, calls: list[dict[str, Any]], trial: Trial, assessment, names) -> Trial:
    request = NarrationInput(assessment=assessment, citations=[])
    start = len(calls)
    for attempt in range(1, MAX_RETRIES + 2):
        trial.attempts = attempt
        try:
            output = narrator.narrate(request, names)
        except NarratorError as e:
            trial.violations.append({"error": str(e)})
            continue
        result = check_narration(output, assessment)
        if result.passed:
            trial.passed_first, trial.fell_back, trial.output = attempt == 1, False, output
            break
        trial.violations.append(result.model_dump(exclude={"passed"}))
    mine = calls[start:]
    trial.seconds = sum(c["seconds"] for c in mine)
    costs = [c["cost"] for c in mine if c["cost"] is not None]
    trial.cost = sum(costs) if costs else None
    return trial


def write_stats(trials: list[Trial], out: Path) -> None:
    lines = ["# LLM 敘述模型比較", "", "| 模型 | 次數 | 一次就通過 | 改用模板 | 平均秒數 | 平均每份費用（USD） |", "|---|---|---|---|---|---|"]
    for model in dict.fromkeys(t.model for t in trials):
        mine = [t for t in trials if t.model == model]
        costs = [t.cost for t in mine if t.cost is not None]
        cost = f"{statistics.mean(costs):.5f}" if costs else "—"
        lines.append(
            f"| {model} | {len(mine)} | {sum(t.passed_first for t in mine) / len(mine):.0%} "
            f"| {sum(t.fell_back for t in mine) / len(mine):.0%} | {statistics.mean(t.seconds for t in mine):.1f} | {cost} |"
        )
    (out / "stats.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_route(text: str) -> Route:
    model, sep, provider = text.rpartition("@")
    if not sep or not model or not provider:
        raise argparse.ArgumentTypeError(f"格式是 型號@服務商，收到 {text!r}")
    return Route(model, provider)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLM 敘述模型比較（會真的呼叫 OpenRouter）")
    parser.add_argument("--model", type=parse_route, action="append", required=True, help="型號@服務商，可給多次")
    parser.add_argument("--case", type=Path, action="append", help="06_assessment 格式的 JSON，可給多次")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("docs/w3/narrator-comparison"))
    args = parser.parse_args(argv)

    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("沒有設定 OPENROUTER_API_KEY", file=sys.stderr)
        return 1
    catalog = get_catalog_source().load()
    names = {i.code: i.display_name_zh for i in catalog.ingredients}
    cases = {p.stem: Assessment.model_validate_json(p.read_text(encoding="utf-8")) for p in args.case or [DEFAULT_CASE]}
    args.out.mkdir(parents=True, exist_ok=True)

    trials: list[Trial] = []
    with (args.out / "runs.jsonl").open("w", encoding="utf-8") as log:
        for route in args.model:
            calls: list[dict[str, Any]] = []
            narrator = OpenRouterNarrator(metered(http_transport(api_key), calls), route)
            for case_name, assessment in cases.items():
                for run in range(1, args.runs + 1):
                    trial = run_trial(narrator, calls, Trial(route.model, case_name, run), assessment, names)
                    trials.append(trial)
                    record = {**trial.__dict__, "output": trial.output and trial.output.model_dump(mode="json")}
                    log.write(json.dumps(record, ensure_ascii=False) + "\n")
                    print(f"{route.model} {case_name} #{run}：{'模板' if trial.fell_back else f'第 {trial.attempts} 次通過'}")
    write_stats(trials, args.out)
    print(f"結果在 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
