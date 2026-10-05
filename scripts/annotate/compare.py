"""逐欄比對兩份標註（D18）：一致／不一致清單、人工抽查名單、Cohen's κ 與完全一致率。

對齊方式：同一張照片內，以「名稱去括號、全形轉半形、去空白」後的字串對齊兩邊的列；
同名出現多次時依出現順序一對一配對。對不上的列整列列為不一致（某一方多抓或漏抓），交人工裁決。

指標：
- 類別欄位（unit、label_section、dose_unit）：Cohen's κ。只用兩邊都有的列計算。
- 數值與文字欄位：完全一致率（κ 不適用連續數值）。名稱以全形轉半形、去空白後比較。
- κ 只說明兩個模型「彼此多一致」，不代表正確；正確率要靠人工抽查估計（見 stats）。

抽查名單：兩邊一致、而且兩邊都有填值的高風險欄位（每一份量、劑型、單位、%、元素量）全部列入；
兩邊都填空白的高風險欄位（例如成分欄賦形劑沒有單位）和其他欄位一起，以固定亂數種子隨機抽
sample_rate 比例（無條件進位），同一份輸入一定產生同一份名單。

列數核對：抽查只看「兩邊都有」的欄位，兩個模型都漏掉（或都多出）的列不會出現在任何清單。
因此每張照片列出兩邊的列數，由人工填照片上實際的列數；實際列數比兩邊都多或都少，就要回去看那張照片。
"""

import csv
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.extraction.textnorm import compact, strip_parenthetical
from scripts.annotate.schema import AnnotatedRow, Annotation, AnnotationRecord

DEFAULT_SEED = 20261007
DEFAULT_SAMPLE_RATE = 0.2  # 比較集 20%；驗收集用 0.3（D18）

ROW_FIELDS = ("raw_name", "per_serving", "unit", "percent_dv", "stated_elemental_amount", "label_section")
SERVING_FIELDS = ("serving_size", "dose_unit")
HIGH_RISK = frozenset({"serving_size", "dose_unit", "unit", "percent_dv", "stated_elemental_amount"})
CATEGORICAL = ("unit", "label_section", "dose_unit")
EXACT = ("raw_name", "per_serving", "percent_dv", "stated_elemental_amount", "serving_size")
ROW_PRESENCE = "row"  # 「這一列存在」本身，只出現在不一致清單
SERVING_ROW = "每一份量"


@dataclass(frozen=True)
class FieldComparison:
    image_id: str
    row: str  # 列的顯示名稱（重複時加 #2），每一份量那欄固定為「每一份量」
    field: str
    a: Any
    b: Any
    agree: bool
    high_risk: bool


@dataclass(frozen=True)
class SpotCheck:
    item: FieldComparison
    reason: str  # high_risk（全查）或 random（隨機抽查）


@dataclass
class ComparisonReport:
    fields: list[FieldComparison]
    spot_checks: list[SpotCheck]
    kappa: dict[str, float | None]  # 無法計算（沒有資料、或兩邊都只用同一個類別）時為 None
    exact_agreement: dict[str, tuple[int, int]]  # 欄位 → (一致數, 比較數)
    rows_paired: int
    rows_unpaired: int
    images_compared: list[str]
    images_only_in: dict[str, list[str]]  # 只有某一方標註的照片，不參與比對
    row_counts: dict[str, tuple[int, int]]  # 照片編號 → (a 的列數, b 的列數)
    seed: int
    sample_rate: float
    names: tuple[str, str] = ("claude", "codex")
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def disagreements(self) -> list[FieldComparison]:
        return [f for f in self.fields if not f.agree]

    @property
    def agreement_rate(self) -> float | None:
        """所有已配對欄位的一致率（不含整列對不上的）。"""
        compared = [f for f in self.fields if f.field != ROW_PRESENCE]
        return sum(f.agree for f in compared) / len(compared) if compared else None


def compare(
    a: dict[str, Annotation],
    b: dict[str, Annotation],
    *,
    seed: int = DEFAULT_SEED,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    names: tuple[str, str] = ("claude", "codex"),
) -> ComparisonReport:
    if not 0 <= sample_rate <= 1:
        raise ValueError("sample_rate 必須介於 0 與 1")
    images = sorted(a.keys() & b.keys())
    fields: list[FieldComparison] = []
    paired = unpaired = 0
    for image_id in images:
        fields += _compare_serving(image_id, a[image_id], b[image_id])
        pairs, leftovers = _pair_rows(a[image_id].rows, b[image_id].rows)
        paired += len(pairs)
        unpaired += len(leftovers)
        for label, row_a, row_b in pairs:
            fields += [_field(image_id, label, f, getattr(row_a, f), getattr(row_b, f)) for f in ROW_FIELDS]
        for label, row_a, row_b in leftovers:
            fields.append(
                FieldComparison(
                    image_id, label, ROW_PRESENCE,
                    row_a.raw_name if row_a else None, row_b.raw_name if row_b else None,
                    agree=False, high_risk=False,
                )
            )  # fmt: skip

    return ComparisonReport(
        fields=fields,
        spot_checks=_spot_checks(fields, seed, sample_rate),
        kappa={f: cohens_kappa([(x.a, x.b) for x in fields if x.field == f]) for f in CATEGORICAL},
        exact_agreement={f: _count([x for x in fields if x.field == f]) for f in EXACT},
        rows_paired=paired,
        rows_unpaired=unpaired,
        images_compared=images,
        images_only_in={names[0]: sorted(a.keys() - b.keys()), names[1]: sorted(b.keys() - a.keys())},
        row_counts={i: (len(a[i].rows), len(b[i].rows)) for i in images},
        seed=seed,
        sample_rate=sample_rate,
        names=names,
    )


def cohens_kappa(pairs: list[tuple[Any, Any]]) -> float | None:
    """κ = (p_o − p_e) / (1 − p_e)。null 視為一個類別（「兩邊都說沒有單位」也是一致）。"""
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(x == y for x, y in pairs) / n
    count_a = Counter(x for x, _ in pairs)
    count_b = Counter(y for _, y in pairs)
    expected = sum(count_a[c] * count_b[c] for c in count_a.keys() | count_b.keys()) / (n * n)
    if expected == 1:  # 兩邊都只用同一個類別，κ 沒有定義
        return None
    return (observed - expected) / (1 - expected)


def _compare_serving(image_id: str, a: Annotation, b: Annotation) -> list[FieldComparison]:
    return [_field(image_id, SERVING_ROW, f, getattr(a.serving, f), getattr(b.serving, f)) for f in SERVING_FIELDS]


def _field(image_id: str, row: str, name: str, a: Any, b: Any) -> FieldComparison:
    return FieldComparison(image_id, row, name, a, b, _same(name, a, b), name in HIGH_RISK)


def _same(name: str, a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if name == "raw_name":
        return compact(a) == compact(b)
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)
    return a == b


Pair = tuple[str, AnnotatedRow | None, AnnotatedRow | None]


def _pair_rows(rows_a: list[AnnotatedRow], rows_b: list[AnnotatedRow]) -> tuple[list[Pair], list[Pair]]:
    """依對齊鍵配對；回傳（配對成功的列, 只有一方有的列），都依 a 的順序、再接 b 剩下的。"""
    by_key_b: dict[str, list[AnnotatedRow]] = defaultdict(list)
    for row in rows_b:
        by_key_b[strip_parenthetical(row.raw_name)].append(row)
    seen: Counter[str] = Counter()
    pairs: list[Pair] = []
    leftovers: list[Pair] = []
    for row in rows_a:
        key = strip_parenthetical(row.raw_name)
        seen[key] += 1
        label = _label(row.raw_name, seen[key])
        candidates = by_key_b[key]
        if candidates:
            pairs.append((label, row, candidates.pop(0)))
        else:
            leftovers.append((label, row, None))
    for key, remaining in by_key_b.items():
        for row in remaining:
            seen[key] += 1
            leftovers.append((_label(row.raw_name, seen[key]), None, row))
    return pairs, leftovers


def _label(raw_name: str, occurrence: int) -> str:
    return raw_name if occurrence == 1 else f"{raw_name}#{occurrence}"


def _count(items: list[FieldComparison]) -> tuple[int, int]:
    return sum(i.agree for i in items), len(items)


def _spot_checks(fields: list[FieldComparison], seed: int, sample_rate: float) -> list[SpotCheck]:
    agreed = [f for f in fields if f.agree]
    full = {i for i, f in enumerate(agreed) if f.high_risk and f.a is not None}  # 兩邊一致，a 有值即兩邊都有值
    others = [i for i in range(len(agreed)) if i not in full]
    k = math.ceil(sample_rate * len(others))
    picked = set(random.Random(seed).sample(others, k))
    return [
        SpotCheck(f, "high_risk" if i in full else "random")
        for i, f in enumerate(agreed)
        if i in full or i in picked
    ]


# ── 讀寫檔案 ─────────────────────────────────────────────────────


def load_annotations(folder: Path) -> tuple[dict[str, Annotation], set[str]]:
    """讀 <folder>/<照片編號>.json，回傳（照片編號 → 標註, 用到的模型）。"""
    annotations: dict[str, Annotation] = {}
    models: set[str] = set()
    for path in sorted(folder.glob("*.json")):
        record = AnnotationRecord.model_validate_json(path.read_text(encoding="utf-8"))
        annotations[record.image_id] = record.annotation
        models.add(record.model)
    return annotations, models


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def write_outputs(report: ComparisonReport, out: Path) -> None:
    """不一致清單與抽查名單寫成 CSV（utf-8-sig，Excel 直接開不會亂碼），附一份 markdown 摘要。"""
    out.mkdir(parents=True, exist_ok=True)
    name_a, name_b = report.names
    with (out / "disagreements.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image_id", "row", "field", name_a, name_b, "adjudicated"])
        for f in report.disagreements:
            writer.writerow([f.image_id, f.row, f.field, _fmt(f.a), _fmt(f.b), ""])
    with (out / "spot_checks.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image_id", "row", "field", "value", "reason", "verdict"])
        for s in report.spot_checks:
            writer.writerow([s.item.image_id, s.item.row, s.item.field, _fmt(s.item.a), s.reason, ""])
    with (out / "row_counts.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image_id", name_a, name_b, "actual_rows"])
        for image_id, (count_a, count_b) in report.row_counts.items():
            writer.writerow([image_id, count_a, count_b, ""])
    (out / "summary.md").write_text(summary_markdown(report), encoding="utf-8")


def summary_markdown(report: ComparisonReport) -> str:
    name_a, name_b = report.names
    lines = [
        "# AI 雙盲標註比對摘要",
        "",
        f"- 比對照片：{len(report.images_compared)} 張",
    ]
    for name, only in report.images_only_in.items():
        if only:
            lines.append(f"- 只有 {name} 標註（未比對）：{', '.join(only)}")
    for key, value in report.extra.items():
        lines.append(f"- {key}：{value}")
    rate = report.agreement_rate
    lines += [
        f"- 列對齊：{report.rows_paired} 列配對成功，{report.rows_unpaired} 列只有一方有",
        f"- 已配對欄位一致率：{_pct(rate)}",
        f"- 不一致（待人工裁決）：{len(report.disagreements)} 項",
        f"- 抽查名單：{len(report.spot_checks)} 項"
        f"（高風險全查 {sum(s.reason == 'high_risk' for s in report.spot_checks)}、"
        f"其他隨機 {sum(s.reason == 'random' for s in report.spot_checks)}；"
        f"比例 {report.sample_rate:.0%}，種子 {report.seed}）",
        "",
        f"## 類別欄位 Cohen's κ（{name_a} vs {name_b}）",
        "",
        "| 欄位 | κ | 樣本數 |",
        "|---|---|---|",
    ]
    for f, k in report.kappa.items():
        n = sum(1 for x in report.fields if x.field == f)
        lines.append(f"| {f} | {'無法計算' if k is None else f'{k:.3f}'} | {n} |")
    lines += ["", "## 數值與文字欄位完全一致率", "", "| 欄位 | 一致率 | 一致／比較 |", "|---|---|---|"]
    for f, (agree, total) in report.exact_agreement.items():
        lines.append(f"| {f} | {_pct(agree / total if total else None)} | {agree}／{total} |")
    lines += ["", "## 每張照片的列數（請在 row_counts.csv 填照片上實際的列數）", "", f"| 照片 | {name_a} | {name_b} |", "|---|---|---|"]
    for image_id, (count_a, count_b) in report.row_counts.items():
        lines.append(f"| {image_id} | {count_a} | {count_b} |")
    lines += ["", "κ 只表示兩個模型彼此多一致，不代表正確；正確率以人工抽查錯誤率估計。", ""]
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


# ── 人工填完抽查名單之後 ─────────────────────────────────────────

_OK = {"ok", "對", "o", "v", "correct"}
_WRONG = {"wrong", "錯", "x", "incorrect"}


def spot_check_stats(path: Path) -> dict[str, tuple[int, int]]:
    """讀人工填好 verdict 的 spot_checks.csv，回傳 reason → (錯誤數, 已檢查數)，另含 all 合計。

    verdict 填「對」或「錯」（也接受 ok／wrong）；空白表示還沒查，不計入。
    """
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            verdict = row["verdict"].strip().lower()
            if not verdict:
                continue
            if verdict not in _OK | _WRONG:
                raise ValueError(f"看不懂的 verdict：{row['verdict']}（請填 對 或 錯）")
            for key in (row["reason"], "all"):
                stats[key][0] += verdict in _WRONG
                stats[key][1] += 1
    return {k: (v[0], v[1]) for k, v in stats.items()}


def row_count_mismatches(path: Path) -> list[tuple[str, int, int, int]]:
    """讀人工填好 actual_rows 的 row_counts.csv，回傳要回去看的照片：(照片, a 列數, b 列數, 實際列數)。

    實際列數比兩邊都多＝兩個模型都漏了列；比兩邊都少＝兩個模型都多抓了列。
    介於兩者之間的差異已經在不一致清單裡（某一方多抓或漏抓），不重複列出。空白表示還沒數，不計入。
    """
    flagged = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        next(reader)  # 表頭的兩欄是標註者名稱，依位置讀
        for image_id, count_a, count_b, actual in reader:
            if not actual.strip():
                continue
            a, b, n = int(count_a), int(count_b), int(actual)
            if n > max(a, b) or n < min(a, b):
                flagged.append((image_id, a, b, n))
    return flagged

