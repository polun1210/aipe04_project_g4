"""產生人工裁決與抽查用的對照頁（D18 的人工步驟）。

一張照片一區：左邊原圖（點一下放大），右邊是這張照片的列數核對、不一致項目與抽查項目。
填完按「匯出」，下載三個填好的 CSV（格式與 compare 輸出的相同），放回比對資料夾就能執行 stats。
頁面只引用本機照片的相對路徑，不嵌入照片，也不進 repo（data/ 已被 .gitignore 排除）。
"""

import csv
import hashlib
import html
import json
import os
from collections import defaultdict
from pathlib import Path

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")

# 頁面上只顯示中文；匯出的 CSV 仍用原始代碼，後續工具才讀得懂
FIELD_ZH = {
    "row": "這一列存不存在",
    "raw_name": "名稱",
    "per_serving": "每份含量",
    "unit": "單位",
    "percent_dv": "每日參考值百分比（%）",
    "stated_elemental_amount": "標示寫明的元素量（例如「含純鈣50mg」的 50）",
    "label_section": "出現在哪個區塊",
    "serving_size": "每一份量（幾粒／幾錠）",
    "dose_unit": "劑型（粒、錠…）",
}
VALUE_ZH = {
    "unit": {"mg": "毫克 mg", "ug": "微克 μg", "g": "公克 g", "kcal": "大卡 kcal", "iu": "IU 國際單位",
             "mg_ate": "毫克 α-TE", "mg_ne": "毫克 NE", "other": "其他單位"},
    "label_section": {"nutrition_table": "營養標示表", "per_unit_note": "每份／每粒含量說明",
                      "ingredient_list": "成分欄", "front": "正面宣傳文字", "other": "其他"},
    "dose_unit": {"capsule": "膠囊", "tablet": "錠", "softgel": "軟膠囊", "gummy": "軟糖", "sachet": "包",
                  "scoop": "匙", "ml": "毫升", "drop": "滴", "g": "公克"},
}


def _zh_field(field: str) -> str:
    return FIELD_ZH.get(field, field)


def _zh_value(field: str, value: str) -> str:
    if value in ("", "null"):
        return "（沒有這一列）" if field == "row" else "（沒寫）"
    return VALUE_ZH.get(field, {}).get(value, value)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_image(images: Path, image_id: str) -> Path | None:
    """副檔名不分大小寫（p01-img01.JPG 也找得到），與 run 的判斷一致；在大小寫敏感的系統上也成立。"""
    if not images.is_dir():
        return None
    for path in sorted(images.iterdir()):
        if path.stem == image_id and path.suffix.lower() in IMAGE_SUFFIXES:
            return path
    return None


def image_problems(comparison: Path, images: Path, recorded: dict[str, set[str]] | None = None) -> list[str]:
    """每個照片編號都要恰好對到一張照片（副檔名不分大小寫），而且照片內容要與標註當時相同。

    recorded：照片編號 → 標註紀錄裡的照片指紋（兩位標註者有記錄的都放進來）。回傳有問題的編號與原因。
    """
    problems = []
    candidates = sorted(images.iterdir()) if images.is_dir() else []
    for row in _read(comparison / "row_counts.csv"):
        hits = [p for p in candidates if p.stem == row["image_id"] and p.suffix.lower() in IMAGE_SUFFIXES]
        if not hits:
            problems.append(f"{row['image_id']} 找不到照片")
        elif len(hits) > 1:
            problems.append(f"{row['image_id']} 有 {len(hits)} 張同名照片")
        elif recorded and recorded.get(row["image_id"]):
            current = hashlib.sha256(hits[0].read_bytes()).hexdigest()
            if recorded[row["image_id"]] != {current}:
                problems.append(f"{row['image_id']} 的照片在標註後被換過")
    return problems


def build_review(
    comparison: Path,
    images: Path,
    notes: dict[str, str] | None = None,
    skip_random: set[str] | None = None,
) -> str:
    """讀 compare 的輸出，回傳對照頁 HTML。

    notes：照片編號 → 要特別提醒裁決者的話。
    skip_random：這些照片的隨機抽查項目不顯示（只做高風險全查）；跳過的項目匯出時 verdict 留空，stats 不計入。
    """
    disagreements = _read(comparison / "disagreements.csv")
    spot_checks = _read(comparison / "spot_checks.csv")
    row_counts = _read(comparison / "row_counts.csv")
    names = list(row_counts[0].keys())[1:3] if row_counts else ["claude", "codex"]

    by_image: dict[str, dict[str, list]] = defaultdict(lambda: {"dis": [], "spot": []})
    for i, row in enumerate(disagreements):
        by_image[row["image_id"]]["dis"].append((i, row))
    skipped = []
    for i, row in enumerate(spot_checks):
        if row["reason"] == "random" and row["image_id"] in (skip_random or set()):
            skipped.append(i)
            by_image[row["image_id"]].setdefault("skipped", 0)
            by_image[row["image_id"]]["skipped"] += 1
            continue
        by_image[row["image_id"]]["spot"].append((i, row))

    sections = []
    for count in row_counts:
        image_id = count["image_id"]
        image = _find_image(images, image_id)
        src = Path(os.path.relpath(image, comparison)).as_posix() if image else ""
        sections.append(_section(image_id, src, count, names, by_image[image_id], (notes or {}).get(image_id)))

    data = {
        "names": names,
        "disagreements": disagreements,
        "spot_checks": spot_checks,
        "row_counts": row_counts,
        "skipped": skipped,
        # 暫存在瀏覽器的結果是依「第幾項」記的；項目清單一變（例如重跑 compare），指紋就不同，
        # 舊的暫存不會被套到別的項目上
        "fingerprint": _fingerprint(disagreements, spot_checks),
    }
    return _PAGE.replace("{{SECTIONS}}", "\n".join(sections)).replace(
        "{{DATA}}", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    )


def _fingerprint(disagreements: list[dict[str, str]], spot_checks: list[dict[str, str]]) -> str:
    # 包含兩邊的值、抽查值與原因（不含人工填的裁決／判斷）：內容一變就換一份暫存
    def content(prefix: str, row: dict[str, str], skip: str) -> str:
        return prefix + "|" + "|".join(f"{k}={v}" for k, v in row.items() if k != skip)

    items = [content("d", r, "adjudicated") for r in disagreements]
    items += [content("s", r, "verdict") for r in spot_checks]
    return hashlib.sha1("\n".join(items).encode("utf-8")).hexdigest()[:12]


def _section(image_id: str, src: str, count: dict, names: list[str], items: dict, note: str | None) -> str:
    e = html.escape
    a, b = names
    dis_rows = "".join(
        f"<tr><td>{e(r['row'])}</td><td>{e(_zh_field(r['field']))}</td>"
        f"<td><button data-pick='{i}' data-value='{e(r[a])}'>{e(_zh_value(r['field'], r[a]))}</button></td>"
        f"<td><button data-pick='{i}' data-value='{e(r[b])}'>{e(_zh_value(r['field'], r[b]))}</button></td>"
        f"<td><input data-dis='{i}' placeholder='點左邊的值，或自己填'></td></tr>"
        for i, r in items["dis"]
    )
    spot_rows = "".join(
        f"<tr><td>{e(r['row'])}</td><td>{e(_zh_field(r['field']))}</td><td>{e(_zh_value(r['field'], r['value']))}</td>"
        f"<td class='{e(r['reason'])}'>{'全查' if r['reason'] == 'high_risk' else '隨機'}</td>"
        f"<td><label><input type='radio' name='s{i}' value='對' data-spot='{i}'>對</label> "
        f"<label><input type='radio' name='s{i}' value='錯' data-spot='{i}'>錯</label></td></tr>"
        for i, r in items["spot"]
    )
    note_html = f"<p class='note'>⚠ {e(note)}</p>" if note else ""
    done = items["dis"] and all(r.get("adjudicated") for _, r in items["dis"])
    dis_hint = "✅ 已經裁決完成，不用再填" if done else "選對的那邊，都不對就自己填；整列多出來的填「刪除」"
    skipped = items.get("skipped", 0)
    skipped_html = f"<p class='skip'>另有隨機抽查 {skipped} 項本次跳過（只做全查）</p>" if skipped else ""
    return f"""
<section id="{e(image_id)}">
  <div class="img"><img src="{e(src)}" alt="{e(image_id)}" onclick="this.classList.toggle('zoom')"></div>
  <div class="work">
    <h2>{e(image_id)}</h2>{note_html}
    <p class="count">列數：{e(a)} {e(count[a])} 列、{e(b)} {e(count[b])} 列；照片上實際
      <input data-count="{e(image_id)}" size="4"> 列（營養標示每一列＋成分欄每一項）</p>
    <h3>不一致（{len(items['dis'])}）：{dis_hint}</h3>
    <table><tr><th>成分（列）</th><th>要確認的項目</th><th>{e(a)} 讀成</th><th>{e(b)} 讀成</th><th>裁決</th></tr>{dis_rows}</table>
    <h3>抽查（{len(items['spot'])}）：兩個 AI 讀到一樣的值，看照片判斷它對不對</h3>
    <table><tr><th>成分（列）</th><th>要確認的項目</th><th>兩個 AI 都讀成</th><th></th><th>照片上是不是這樣？</th></tr>{spot_rows}</table>{skipped_html}
  </div>
</section>"""


_PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>標註裁決與抽查</title>
<style>
:root { --bg:#fff; --fg:#222; --line:#ddd; --accent:#0a6; --warn:#b60; }
body { margin:0; font:14px/1.5 system-ui, "Microsoft JhengHei", sans-serif; background:var(--bg); color:var(--fg); }
header { position:sticky; top:0; z-index:2; background:#f4f6f8; border-bottom:1px solid var(--line); padding:8px 16px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
section { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.1fr); gap:16px; padding:16px; border-bottom:2px solid var(--line); }
.img img { width:100%; position:sticky; top:56px; cursor:zoom-in; }
.img img.zoom { position:fixed; inset:0; width:auto; max-width:none; height:100vh; margin:auto; z-index:5; background:#000; cursor:zoom-out; }
table { border-collapse:collapse; width:100%; margin-bottom:12px; }
td, th { border:1px solid var(--line); padding:3px 6px; vertical-align:top; word-break:break-all; }
button { font:inherit; text-align:left; cursor:pointer; background:#fff; border:1px solid #bbb; border-radius:4px; }
button.on { background:#dff5ea; border-color:var(--accent); }
td.high_risk { color:var(--warn); }
.skip { color:#777; }
.note { background:#fff4e0; padding:6px 8px; border-left:4px solid var(--warn); }
#progress { font-weight:600; }
@media (max-width:800px) { section { grid-template-columns:1fr; } .img img { position:static; } }
</style></head><body>
<header><strong>標註裁決與抽查</strong><span id="progress"></span>
<span>匯出（瀏覽器會擋連續下載，請一個一個按）：</span>
<button id="export-spot">① 抽查結果</button><button id="export-dis">② 不一致裁決</button><button id="export-count">③ 列數</button>
<span>填寫內容會暫存在這個瀏覽器</span></header>
{{SECTIONS}}
<script>
const DATA = {{DATA}};
const KEY = "annotate-review:" + location.pathname + ":" + DATA.fingerprint;
let state = { dis:{}, spot:{}, count:{} };
try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}
// 已經填在 CSV 裡的值（例如在對話中裁決過的）當作初始值，避免匯出時被空白蓋掉
DATA.disagreements.forEach((r, i) => { if (!state.dis[i] && r.adjudicated) state.dis[i] = r.adjudicated; });
const SKIPPED = new Set(DATA.skipped);
SKIPPED.forEach(i => { delete state.spot[i]; });  // 跳過的項目不沿用任何舊答案
DATA.spot_checks.forEach((r, i) => { if (!SKIPPED.has(i) && !state.spot[i] && r.verdict) state.spot[i] = r.verdict; });
DATA.row_counts.forEach(r => { if (!state.count[r.image_id] && r.actual_rows) state.count[r.image_id] = r.actual_rows; });
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} progress(); };
function progress() {
  const d = Object.values(state.dis).filter(v => v).length, c = Object.values(state.count).filter(v => v).length;
  const skip = new Set(DATA.skipped), s = Object.keys(state.spot).filter(i => !skip.has(Number(i))).length;
  document.getElementById("progress").textContent =
    `不一致 ${d}/${DATA.disagreements.length}　抽查 ${s}/${DATA.spot_checks.length - DATA.skipped.length}　列數 ${c}/${DATA.row_counts.length}`;
}
document.querySelectorAll("[data-dis]").forEach(el => {
  el.value = state.dis[el.dataset.dis] || "";
  el.oninput = () => { state.dis[el.dataset.dis] = el.value; mark(el.dataset.dis); save(); };
});
function mark(i) {
  document.querySelectorAll(`[data-pick='${i}']`).forEach(b => b.classList.toggle("on", b.dataset.value === state.dis[i]));
}
document.querySelectorAll("[data-pick]").forEach(b => {
  b.onclick = () => { const i = b.dataset.pick; state.dis[i] = b.dataset.value; document.querySelector(`[data-dis='${i}']`).value = b.dataset.value; mark(i); save(); };
});
Object.keys(state.dis).forEach(mark);
document.querySelectorAll("[data-spot]").forEach(r => {
  r.checked = state.spot[r.dataset.spot] === r.value;
  r.onchange = () => { state.spot[r.dataset.spot] = r.value; save(); };
});
document.querySelectorAll("[data-count]").forEach(el => {
  el.value = state.count[el.dataset.count] || "";
  el.oninput = () => { state.count[el.dataset.count] = el.value.trim(); save(); };
});
function csv(rows, header) {
  const q = v => /[",\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  return "\\ufeff" + [header, ...rows.map(r => header.map(h => r[h] ?? ""))].map(r => r.map(v => q(String(v))).join(",")).join("\\r\\n") + "\\r\\n";
}
function download(name, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type:"text/csv" }));
  a.download = name; a.click();
}
const [A, B] = DATA.names;
document.getElementById("export-dis").onclick = () => {
  const [a, b] = [A, B];
  download("disagreements.csv", csv(DATA.disagreements.map((r, i) => ({ ...r, adjudicated: state.dis[i] || "" })),
    ["image_id", "row", "field", a, b, "adjudicated"]));
};
document.getElementById("export-spot").onclick = () => {
  download("spot_checks.csv", csv(DATA.spot_checks.map((r, i) => ({ ...r, verdict: SKIPPED.has(i) ? "" : (state.spot[i] || "") })),
    ["image_id", "row", "field", "value", "reason", "verdict"]));
};
document.getElementById("export-count").onclick = () => {
  const [a, b] = [A, B];
  download("row_counts.csv", csv(DATA.row_counts.map(r => ({ ...r, actual_rows: state.count[r.image_id] || "" })),
    ["image_id", a, b, "actual_rows"]));
};
progress();
</script></body></html>
"""
