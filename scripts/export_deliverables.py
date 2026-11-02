"""從 data/catalog/ 匯出老師要的交付物到 build/deliverables/，並檢查引用是否完整。

    uv run python scripts/export_deliverables.py [--out build/deliverables]

輸出：rules.csv（規則清單，含狀態與覆核欄）、citations.csv（引用來源）、VERSION（資料版本）。
檢查：citations.csv 的 url 欄空白的列；規則引用了但 citations.csv 沒有的 citation_id。
有問題時只列出、結束碼為 1，不會自動補。
"""

import argparse
import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "catalog"
DEFAULT_OUT = ROOT / "build" / "deliverables"
FILES = ("rules.csv", "citations.csv", "VERSION")
CITATION_SEPARATOR = "|"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def find_missing_urls(citations: list[dict[str, str]]) -> list[str]:
    return [c["citation_id"] for c in citations if not c["url"].strip()]


def find_dangling_citations(rules: list[dict[str, str]], citations: list[dict[str, str]]) -> dict[str, list[str]]:
    """回傳 {rule_id: [不存在的 citation_id]}，只列有問題的規則。"""
    known = {c["citation_id"] for c in citations}
    result: dict[str, list[str]] = {}
    for rule in rules:
        ids = [i.strip() for i in rule["citation_ids"].split(CITATION_SEPARATOR) if i.strip()]
        missing = [i for i in ids if i not in known]
        if missing:
            result[rule["rule_id"]] = missing
    return result


def export(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copyfile(CATALOG / name, out / name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    export(args.out)
    rules = read_rows(CATALOG / "rules.csv")
    citations = read_rows(CATALOG / "citations.csv")
    version = (CATALOG / "VERSION").read_text(encoding="utf-8").strip()

    print(f"資料版本 {version}：規則 {len(rules)} 條、引用 {len(citations)} 筆 -> {args.out}")
    statuses: dict[str, int] = {}
    for rule in rules:
        statuses[rule["status"]] = statuses.get(rule["status"], 0) + 1
    print("規則狀態：" + "、".join(f"{k} {v}" for k, v in sorted(statuses.items())))
    unreviewed = [r["rule_id"] for r in rules if not r["reviewed_by"].strip() or not r["reviewed_at"].strip()]
    print(f"覆核欄（reviewed_by／reviewed_at）有空白的規則：{unreviewed or '無'}")

    missing_urls = find_missing_urls(citations)
    dangling = find_dangling_citations(rules, citations)
    print(f"url 欄空白的引用：{missing_urls or '無'}")
    print(f"規則引用但不存在的 citation_id：{dangling or '無'}")
    return 1 if missing_urls or dangling else 0


if __name__ == "__main__":
    sys.exit(main())
