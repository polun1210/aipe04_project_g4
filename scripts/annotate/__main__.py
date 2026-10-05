"""uv run python -m scripts.annotate {run,compare,stats} ...（說明見 scripts/annotate/__init__.py）"""

import argparse
import sys
from pathlib import Path

from scripts.annotate.compare import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SEED,
    compare,
    load_annotations,
    row_count_mismatches,
    spot_check_stats,
    summary_markdown,
    write_outputs,
)
from scripts.annotate.run import annotate_all

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def cmd_run(args: argparse.Namespace) -> int:
    images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if args.only:
        images = [p for p in images if p.stem in set(args.only)]
    if not images:
        print(f"{args.images} 裡沒有照片", file=sys.stderr)
        return 2
    models = {"claude": args.claude_model, "codex": args.codex_model}
    models = {k: v for k, v in models.items() if k in args.annotators}
    missing = [k for k, v in models.items() if not v]
    if missing:  # D20：模型版本必須明確指定並記錄，不用工具的預設值
        print(f"請用 --{missing[0]}-model 指定 {missing[0]} 使用的模型", file=sys.stderr)
        return 2
    failed = annotate_all(images, args.annotations, models, force=args.force)
    if failed:
        print(f"{len(failed)} 項失敗：{', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a, models_a = load_annotations(args.annotations / "claude")
    b, models_b = load_annotations(args.annotations / "codex")
    report = compare(a, b, seed=args.seed, sample_rate=args.sample_rate)
    report.extra["claude 模型"] = "、".join(sorted(models_a)) or "—"
    report.extra["codex 模型"] = "、".join(sorted(models_b)) or "—"
    write_outputs(report, args.out)
    print(summary_markdown(report))
    print(f"已寫出 {args.out / 'disagreements.csv'}、{args.out / 'spot_checks.csv'}、{args.out / 'summary.md'}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    stats = spot_check_stats(args.spot_checks)
    labels = {"high_risk": "高風險欄位（全查）", "random": "其他欄位（隨機抽查）", "all": "合計"}
    for key, label in labels.items():
        wrong, checked = stats.get(key, (0, 0))
        rate = f"{wrong / checked:.1%}" if checked else "—"
        print(f"{label}：抽查錯誤率 {rate}（{wrong}／{checked}，n = {checked}）")
    row_counts = args.spot_checks.parent / "row_counts.csv"
    if row_counts.exists():
        flagged = row_count_mismatches(row_counts)
        for image_id, a, b, n in flagged:
            print(f"列數對不上，請回去看照片：{image_id}（兩邊 {a}、{b} 列，實際 {n} 列）")
        if not flagged:
            print("已填的列數都在兩邊之間，沒有兩邊都漏掉或都多出的列")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.annotate", description="AI 雙盲標註工具")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="請 Claude Code 與 Codex CLI 各自標註（使用本機訂閱）")
    run.add_argument("--images", type=Path, default=Path("data/images"))
    run.add_argument("--annotations", type=Path, default=Path("data/annotations"), help="輸出資料夾")
    run.add_argument("--claude-model", help="傳給 claude --model 的值，會寫入標註紀錄")
    run.add_argument("--codex-model", help="傳給 codex --model 的值，會寫入標註紀錄")
    run.add_argument("--annotators", nargs="+", choices=["claude", "codex"], default=["claude", "codex"])
    run.add_argument("--only", nargs="+", metavar="IMAGE_ID")
    run.add_argument("--force", action="store_true", help="已標註的也重做")
    run.set_defaults(func=cmd_run)

    cmp_ = sub.add_parser("compare", help="逐欄比對兩份標註")
    cmp_.add_argument("--annotations", type=Path, default=Path("data/annotations"))
    cmp_.add_argument("--out", type=Path, default=Path("data/annotations/comparison"))
    cmp_.add_argument("--seed", type=int, default=DEFAULT_SEED)
    cmp_.add_argument("--sample-rate", type=float, default=DEFAULT_SAMPLE_RATE, help="比較集 0.2、驗收集 0.3")
    cmp_.set_defaults(func=cmd_compare)

    stats = sub.add_parser("stats", help="人工填完 spot_checks.csv 的 verdict 後，算抽查錯誤率")
    stats.add_argument("--spot-checks", type=Path, default=Path("data/annotations/comparison/spot_checks.csv"))
    stats.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
