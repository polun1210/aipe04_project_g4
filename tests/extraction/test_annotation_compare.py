"""雙盲標註比對：從對外入口 compare() 測，用手算過的小案例驗算 κ 與一致率。"""

import csv

import pytest

from app.schemas.enums import DoseUnit, LabelSection, Unit
from scripts.annotate.review import build_review
from scripts.annotate.compare import cohens_kappa, compare, row_count_mismatches, spot_check_stats, write_outputs
from scripts.annotate.schema import AnnotatedRow, AnnotatedServing, Annotation

NT = LabelSection.NUTRITION_TABLE


def row(name, amount, unit, pdv=None, elemental=None, section=NT) -> AnnotatedRow:
    return AnnotatedRow(
        raw_name=name,
        per_serving=amount,
        unit=unit,
        percent_dv=pdv,
        stated_elemental_amount=elemental,
        label_section=section,
    )


def annotation(*rows, serving=(2, DoseUnit.CAPSULE)) -> Annotation:
    return Annotation(serving=AnnotatedServing(serving_size=serving[0], dose_unit=serving[1]), rows=list(rows))


# 手算案例（同一張照片，4 列）：
#   維生素D：兩邊一致（b 的名稱用全形 Ｄ 加空白）
#   鈣    ：兩邊一致
#   鎂    ：每份含量不一致（100 vs 120）
#   鋅    ：單位不一致（mg vs ug）
# unit 配對 (ug,ug)(mg,mg)(mg,mg)(mg,ug)：p_o = 3/4；a 有 ug 1、mg 3，b 有 ug 2、mg 2
#   p_e = (1×2 + 3×2) / 16 = 1/2 → κ = (3/4 − 1/2) / (1 − 1/2) = 0.5
A = annotation(
    row("維生素D", 10, Unit.UG, pdv=100),
    row("鈣", 200, Unit.MG, pdv=25, elemental=200),
    row("鎂", 100, Unit.MG),
    row("鋅", 15, Unit.MG),
)
B = annotation(
    row("維生素 Ｄ", 10, Unit.UG, pdv=100),
    row("鈣", 200, Unit.MG, pdv=25, elemental=200),
    row("鎂", 120, Unit.MG),
    row("鋅", 15, Unit.UG),
)


@pytest.fixture
def report():
    return compare({"p01-img01": A}, {"p01-img01": B})


# ── κ 與一致率 ─────────────────────────────────────────────────────


def test_單位的κ符合手算結果(report):
    assert report.kappa["unit"] == pytest.approx(0.5)


def test_兩邊都只用同一個類別時κ無法計算(report):
    assert report.kappa["label_section"] is None  # 四列都是 nutrition_table，p_e = 1


def test_κ在完全一致且有兩個類別時為1():
    assert cohens_kappa([("mg", "mg"), ("ug", "ug")]) == pytest.approx(1.0)


def test_κ在一致程度和隨機相同時為0():
    # p_o = 1/2；a、b 各一半 mg 一半 ug → p_e = 1/2
    assert cohens_kappa([("mg", "mg"), ("mg", "ug"), ("ug", "mg"), ("ug", "ug")]) == pytest.approx(0.0)


def test_沒有樣本時κ無法計算():
    assert cohens_kappa([]) is None


def test_每份含量完全一致率符合手算結果(report):
    assert report.exact_agreement["per_serving"] == (3, 4)


def test_名稱只差全形半形與空白時視為一致(report):
    assert report.exact_agreement["raw_name"] == (4, 4)


def test_整體一致率只計已配對欄位(report):
    # 每一份量 2 欄 ＋ 4 列 × 6 欄 = 26 欄，不一致 2 欄
    assert report.agreement_rate == pytest.approx(24 / 26)


# ── 一致／不一致清單 ───────────────────────────────────────────────


def test_不一致清單列出不一致的欄位與兩邊的值(report):
    found = {(d.row, d.field, d.a, d.b) for d in report.disagreements}
    assert found == {("鎂", "per_serving", 100, 120), ("鋅", "unit", Unit.MG, Unit.UG)}


def test_只有一方有的列整列列為不一致():
    a = annotation(row("鈣", 200, Unit.MG), row("鐵", 10, Unit.MG))
    b = annotation(row("鈣", 200, Unit.MG), row("鋅", 15, Unit.MG))
    rows = {(d.row, d.a, d.b) for d in compare({"p": a}, {"p": b}).disagreements if d.field == "row"}
    assert rows == {("鐵", "鐵", None), ("鋅", None, "鋅")}


def test_括號內容不同的列仍對齊但名稱不一致():
    a = annotation(row("鈣(碳酸鈣)", 200, Unit.MG))
    b = annotation(row("鈣", 200, Unit.MG))
    report = compare({"p": a}, {"p": b})
    assert report.rows_paired == 1
    assert [(d.field, d.a, d.b) for d in report.disagreements] == [("raw_name", "鈣(碳酸鈣)", "鈣")]


def test_同名的列依出現順序配對():
    a = annotation(row("鈣", 200, Unit.MG, section=NT), row("鈣", 50, Unit.MG, section=LabelSection.FRONT))
    b = annotation(row("鈣", 200, Unit.MG, section=NT), row("鈣", 50, Unit.MG, section=LabelSection.FRONT))
    report = compare({"p": a}, {"p": b})
    assert report.disagreements == []
    assert {f.row for f in report.fields} >= {"鈣", "鈣#2"}


def test_每一份量也逐欄比對():
    report = compare({"p": annotation(serving=(2, DoseUnit.CAPSULE))}, {"p": annotation(serving=(1, DoseUnit.CAPSULE))})
    assert [(d.row, d.field) for d in report.disagreements] == [("每一份量", "serving_size")]


def test_只有一方標註的照片不比對並列出():
    report = compare({"p01": A, "p02": A}, {"p01": B, "p03": B})
    assert report.images_compared == ["p01"]
    assert report.images_only_in == {"claude": ["p02"], "codex": ["p03"]}


# ── 抽查名單 ───────────────────────────────────────────────────────


def test_一致且有值的高風險欄位全部列入抽查(report):
    # 每一份量 2 ＋ unit 一致 3 ＋ percent_dv 有值 2 ＋ 元素量有值 1 = 8
    high = [s for s in report.spot_checks if s.reason == "high_risk"]
    assert len(high) == 8
    assert all(s.item.a is not None for s in high)


def test_兩邊都空白的高風險欄位改為隨機抽查(report):
    # percent_dv 兩邊空白 2 ＋ 元素量兩邊空白 3 = 5，不在全查名單
    blank_high = [s for s in report.spot_checks if s.item.high_risk and s.item.a is None]
    assert all(s.reason == "random" for s in blank_high)


def test_其他欄位依比例無條件進位抽查(report):
    # 名稱 4 ＋ 每份含量 3 ＋ 區塊 4 ＋ 兩邊空白的高風險欄位 5 = 16，20% → 3.2 → 4
    assert sum(s.reason == "random" for s in report.spot_checks) == 4


def test_不一致的欄位不列入抽查(report):
    assert all(s.item.agree for s in report.spot_checks)


def test_同一個種子產生同一份抽查名單():
    first = compare({"p": A}, {"p": B}, seed=42).spot_checks
    again = compare({"p": A}, {"p": B}, seed=42).spot_checks
    assert first == again


def test_換種子會換抽到的欄位():
    picks = {
        tuple((s.item.row, s.item.field) for s in compare({"p": A}, {"p": B}, seed=seed).spot_checks)
        for seed in range(5)
    }
    assert len(picks) > 1


def test_抽查比例超出範圍時報錯():
    with pytest.raises(ValueError):
        compare({"p": A}, {"p": B}, sample_rate=1.5)


# ── 輸出檔與人工抽查後的錯誤率 ─────────────────────────────────────


def test_輸出不一致清單與抽查名單供人工填寫(report, tmp_path):
    write_outputs(report, tmp_path)
    with (tmp_path / "disagreements.csv").open(encoding="utf-8-sig") as fh:
        assert len(list(csv.DictReader(fh))) == 2
    with (tmp_path / "spot_checks.csv").open(encoding="utf-8-sig") as fh:
        assert len(list(csv.DictReader(fh))) == 12  # 高風險全查 8 ＋ 隨機 4
    assert "0.500" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_抽查錯誤率依人工填的結果計算且未填的不計入(report, tmp_path):
    write_outputs(report, tmp_path)
    path = tmp_path / "spot_checks.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for i, r in enumerate(rows):
        r["verdict"] = "錯" if i == 0 else ("對" if i < 10 else "")  # 第 1 項錯、2–10 項對、其餘未查
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert spot_check_stats(path)["all"] == (1, 10)


# ── 列數核對：兩個模型都漏掉的列 ─────────────────────────────────


def test_每張照片列出兩邊的列數(report):
    assert report.row_counts == {"p01-img01": (4, 4)}


def _fill_actual(tmp_path, actual_by_image):
    path = tmp_path / "row_counts.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    for r in rows[1:]:
        r[3] = str(actual_by_image.get(r[0], ""))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return path


def test_實際列數比兩邊都多時列出該照片(tmp_path):
    report = compare({"p01-img01": A, "p02-img01": A}, {"p01-img01": B, "p02-img01": B})
    write_outputs(report, tmp_path)
    path = _fill_actual(tmp_path, {"p01-img01": 5, "p02-img01": 4})
    assert row_count_mismatches(path) == [("p01-img01", 4, 4, 5)]


def test_實際列數介於兩邊之間時不重複列出(tmp_path):
    report = compare({"p01-img01": A}, {"p01-img01": annotation(*B.rows[:3])})
    write_outputs(report, tmp_path)
    assert row_count_mismatches(_fill_actual(tmp_path, {"p01-img01": 4})) == []


def test_實際列數未填的照片不計入(report, tmp_path):
    write_outputs(report, tmp_path)
    assert row_count_mismatches(tmp_path / "row_counts.csv") == []


# ── 對照頁 ───────────────────────────────────────────────────────


def test_對照頁列出每張照片的不一致與抽查項目並引用本機照片(report, tmp_path):
    out, images = tmp_path / "comparison", tmp_path / "images"
    images.mkdir()
    (images / "p01-img01.jpg").write_bytes(b"fake-jpeg")
    write_outputs(report, out)
    page = build_review(out, images)
    assert '<section id="p01-img01">' in page
    assert 'src="../images/p01-img01.jpg"' in page  # 相對路徑，不嵌入照片
    assert "不一致（2）" in page and "抽查（12）" in page


def test_對照頁以CSV已填的值為初始值(report, tmp_path):
    out = tmp_path / "comparison"
    write_outputs(report, out)
    page = build_review(out, tmp_path)
    assert "r.adjudicated" in page and "r.actual_rows" in page  # 已裁決的結果不會在匯出時被空白蓋掉


def test_對照頁的欄位與代碼以中文顯示(report, tmp_path):
    out = tmp_path / "comparison"
    write_outputs(report, out)
    page = build_review(out, tmp_path)
    assert "每份含量" in page and "微克 μg" in page and "每一份量（幾粒／幾錠）" in page and "膠囊" in page
    assert "data-value='ug'" in page  # 匯出仍用原始代碼

