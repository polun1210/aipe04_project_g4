"""RAG 檢索評估：每題的預期原文段落有沒有出現在檢索結果的前 N 名（預設 8）。

  離線檢查題目本身（預期原文真的在 data/sources/ 裡，不花錢、不需要資料庫）：
      uv run python evals/rag/run.py --dry-run
  打真的 embedding 與資料庫（需要 .env 的 OPENROUTER_API_KEY、EMBEDDING_MODEL、DATABASE_URL，
  且資料庫已用同一個型號 ingest 過：uv run python -m app.rag.ingest）：
      uv run python evals/rag/run.py --live [--limit 8] [--cases evals/rag/cases_neutral.json]

cases.json 是開發題組；cases_neutral.json 是中立題組，用來比較不同檢索做法，出題規則：
  - 題目來源：NIH ODS HP 的 Interactions with Medications 小節與 NCCIH 頁面中，藥物在 drug_items 裡的組合；
    不看規則有沒有審定、不看哪種檢索做法找得到。
  - 預期段落只用進 git 的 data/sources/，任何人都能重現。
  - --live 只吃代碼，不讀問句（question 只是給人看的）。
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from app.rag.corpus import SOURCES_DIR  # noqa: E402
from app.rag.evaluation import RagCase, load_cases, score_retrieval, validate_against_corpus  # noqa: E402


def _dry_run(cases: list[RagCase], sources_dir: Path) -> int:
    bad = 0
    for case in cases:
        problems = validate_against_corpus(case, sources_dir)
        bad += bool(problems)
        print(f"{case.id}: {'ok' if not problems else '; '.join(problems)}")
    return 1 if bad else 0


def _live(cases: list[RagCase], limit: int) -> int:
    import psycopg
    from dotenv import load_dotenv

    from app.db.config import database_url
    from app.rag.embedder import embedder_from_env
    from app.rag.search import retrieve_evidence

    load_dotenv()
    embedder = embedder_from_env()
    found = total = full = 0
    with psycopg.connect(database_url()) as conn:
        for case in cases:
            evidence = retrieve_evidence(
                conn, embedder, case.ingredient_code, case.drug_ingredient_codes, limit=limit
            )
            score = score_retrieval(case, evidence)
            found, total, full = found + score.found, total + score.total, full + (score.found == score.total)
            print(f"{case.id}: 前 {limit} 名找到預期段落 {score.found}/{score.total}")
    print(f"\n型號 {embedder.model}、前 {limit} 名")
    print(f"預期段落命中：{found}/{total}（{found / total:.0%}）；整題命中：{full}/{len(cases)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=HERE / "cases.json")
    parser.add_argument("--sources", type=Path, default=SOURCES_DIR)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=8, help="每個問題檢索幾個段落")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設不是 UTF-8

    cases = load_cases(args.cases)
    return _dry_run(cases, args.sources) if args.dry_run else _live(cases, args.limit)


if __name__ == "__main__":
    sys.exit(main())
