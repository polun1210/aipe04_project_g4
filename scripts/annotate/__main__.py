"""uv run python -m scripts.annotate {run,compare,stats} ...（說明見 scripts/annotate/__init__.py）"""

import argparse
import sys
from pathlib import Path

from scripts.annotate.compare import (
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SEED,
    compare,
    image_hashes,
    load_annotations,
    mismatched_images,
    row_count_mismatches,
    spot_check_stats,
    summary_markdown,
    write_outputs,
)
from scripts.annotate.gold import GoldError, adjudicate, build_gold, draft_name_map, write_name_map
from scripts.annotate.gold import _read as read_csv
from scripts.annotate.name_review import build_name_review
from scripts.annotate.review import build_review, image_problems
from scripts.annotate.run import annotate_all

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def cmd_run(args: argparse.Namespace) -> int:
    images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if args.only:
        images = [p for p in images if p.stem in set(args.only)]
    if not images:
        print(f"{args.images} 裡沒有照片", file=sys.stderr)
        return 2
    stems = [p.stem for p in images]
    duplicated = sorted({s for s in stems if stems.count(s) > 1})
    if duplicated:  # 照片編號取自檔名，同名不同副檔名會互相覆蓋或被當成已標註
        print(f"照片編號重複（同名不同副檔名）：{', '.join(duplicated)}", file=sys.stderr)
        return 2
    models = {"claude": args.claude_model, "codex": args.codex_model}
    models = {k: v for k, v in models.items() if k in args.annotators}
    missing = [k for k, v in models.items() if not v]
    if missing:  # 模型版本必須明確指定並記錄，不用工具的預設值
        print(f"請用 --{missing[0]}-model 指定 {missing[0]} 使用的模型", file=sys.stderr)
        return 2
    failed = annotate_all(images, args.annotations, models, force=args.force)
    if failed:
        print(f"{len(failed)} 項失敗：{', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a, models_a = load_annotations(args.annotations / "claude", "claude")
    b, models_b = load_annotations(args.annotations / "codex", "codex")
    differ = mismatched_images(image_hashes(args.annotations / "claude"), image_hashes(args.annotations / "codex"))
    if differ:
        print(f"兩位標註者看的照片內容不同（照片中途被換過）：{', '.join(differ)}；請用 --force 重新標註", file=sys.stderr)
        return 2
    if not a or not b or not (a.keys() & b.keys()):
        print("兩個標註者都要有標註，且至少要有一張共同的照片才能比對（請檢查資料夾路徑或標註是否失敗）", file=sys.stderr)
        return 2
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


def cmd_review(args: argparse.Namespace) -> int:
    recorded: dict[str, set[str]] = {}
    for annotator in ("claude", "codex"):
        for image_id, digest in image_hashes(args.annotations / annotator).items():
            if digest:
                recorded.setdefault(image_id, set()).add(digest)
    problems = image_problems(args.comparison, args.images, recorded)
    if problems:  # 沒有照片或照片不確定時不產生頁面，避免在錯的照片上裁決
        print("照片有問題，不產生對照頁：" + "；".join(problems), file=sys.stderr)
        return 2
    out = args.comparison / "review.html"
    out.write_text(build_review(args.comparison, args.images, skip_random=set(args.skip_random or [])), encoding="utf-8")
    print(f"已寫出 {out}；用瀏覽器打開，填完按「匯出」，把三個 CSV 放回 {args.comparison}")
    return 0


def _adjudicated(args: argparse.Namespace):
    a, _ = load_annotations(args.annotations / "claude", "claude")
    b, _ = load_annotations(args.annotations / "codex", "codex")
    c = args.annotations / "comparison"
    return adjudicate(a, b, read_csv(c / "disagreements.csv"), read_csv(c / "spot_checks.csv"), read_csv(c / "corrections.csv"))


def cmd_gold_map(args: argparse.Namespace) -> int:
    try:
        gold = _adjudicated(args)
    except GoldError as e:
        print(e, file=sys.stderr)
        return 1
    rows = draft_name_map(gold, args.catalog)
    out = args.annotations / "gold"
    write_name_map(rows, out / "name_map_draft.csv")
    (out / "name_review.html").write_text(build_name_review(rows), encoding="utf-8")
    print(f"已寫出 {out / 'name_review.html'}；確認後匯出 name_map.csv，放到 {out}")
    return 0


def cmd_gold_build(args: argparse.Namespace) -> int:
    name_map = read_csv(args.annotations / "gold" / "name_map.csv")
    if not name_map:
        print("找不到人工確認過的 name_map.csv（先執行 gold-map 並在確認頁匯出）", file=sys.stderr)
        return 2
    try:
        drafts = build_gold(_adjudicated(args), name_map, read_csv(args.sources))
    except GoldError as e:
        print(e, file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for product, draft in drafts.items():
        (args.out / f"{product}.json").write_text(draft.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    print(f"已寫出 {len(drafts)} 份標準答案到 {args.out}")
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

    review = sub.add_parser("review", help="產生人工裁決與抽查用的對照頁（HTML）")
    review.add_argument("--comparison", type=Path, default=Path("data/annotations/comparison"))
    review.add_argument("--images", type=Path, default=Path("data/images"))
    review.add_argument("--annotations", type=Path, default=Path("data/annotations"), help="核對照片指紋用")
    review.add_argument("--skip-random", nargs="+", metavar="IMAGE_ID", help="這些照片只做全查，隨機抽查項目跳過")
    review.set_defaults(func=cmd_review)

    gmap = sub.add_parser("gold-map", help="合併裁決，產生名稱對照表草稿與確認頁")
    gmap.add_argument("--annotations", type=Path, default=Path("data/annotations"))
    gmap.add_argument("--catalog", type=Path, default=Path("docs/schemas/examples/catalog/ingredients.csv"))
    gmap.set_defaults(func=cmd_gold_map)

    gbuild = sub.add_parser("gold-build", help="用確認過的名稱對照表產生標準答案（辨識草稿結構）")
    gbuild.add_argument("--annotations", type=Path, default=Path("data/annotations"))
    gbuild.add_argument("--sources", type=Path, default=Path("tests/fixtures/labels/sources.csv"))
    gbuild.add_argument("--out", type=Path, default=Path("tests/fixtures/labels"))
    gbuild.set_defaults(func=cmd_gold_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
