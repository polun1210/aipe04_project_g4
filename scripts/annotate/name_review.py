"""名稱對照表的確認頁：每個（名稱, 區塊）選範圍狀態與標準代碼，全中文顯示，匯出 name_map.csv。"""

import html
import json

from app.schemas.enums import IngredientCode
from scripts.annotate.gold import NAME_MAP_FIELDS
from scripts.annotate.review import VALUE_ZH

CODE_ZH = {
    "calcium": "鈣", "magnesium": "鎂", "iron": "鐵", "zinc": "鋅", "potassium": "鉀",
    "vitamin_d": "維生素 D", "vitamin_e": "維生素 E", "vitamin_b12": "維生素 B12", "folate": "葉酸",
    "niacin": "菸鹼素", "vitamin_c": "維生素 C", "vitamin_b6": "維生素 B6", "selenium": "硒",
    "red_yeast_rice": "紅麴（允許成分）", "glucosamine": "葡萄糖胺（允許成分）", "omega_3": "魚油 n-3（允許成分）",
}  # fmt: skip
SCOPE_ZH = {"in_scope": "範圍內（要評估）", "out_of_scope": "範圍外（知道是什麼，不評估）", "unresolved": "無法確認"}
GROUP_ZH = {
    "check": "待確認：請逐一判斷",
    "in_scope": "建議範圍內：請確認對到的營養素對不對",
    "out_of_scope": "建議範圍外：掃一眼，沒問題就不用動",
}


def build_name_review(rows: list[dict[str, str]]) -> str:
    e = html.escape
    sections = []
    for group, title in GROUP_ZH.items():
        items = [(i, r) for i, r in enumerate(rows) if r["group"] == group]
        if not items:
            continue
        body = "".join(_row(i, r) for i, r in items)
        sections.append(
            f"<h2>{e(title)}（{len(items)}）</h2><table><tr><th>照片上的名稱</th><th>出現在</th><th>照片</th>"
            f"<th>範圍狀態</th><th>對到哪個營養素</th><th>型態</th><th>說明</th></tr>{body}</table>"
        )
    return _PAGE.replace("{{BODY}}", "\n".join(sections)).replace(
        "{{DATA}}", json.dumps({"rows": rows, "fields": NAME_MAP_FIELDS}, ensure_ascii=False).replace("</", "<\\/")
    )


def _row(i: int, r: dict[str, str]) -> str:
    e = html.escape
    scope = "".join(
        f"<option value='{k}'{' selected' if k == r['scope_status'] else ''}>{e(v)}</option>" for k, v in SCOPE_ZH.items()
    )
    codes = "<option value=''>（無）</option>" + "".join(
        f"<option value='{c.value}'{' selected' if c.value == r['standard_code'] else ''}>{e(CODE_ZH[c.value])}</option>"
        for c in IngredientCode
    )
    section = VALUE_ZH["label_section"].get(r["label_section"], r["label_section"])
    return (
        f"<tr><td>{e(r['raw_name'])}</td><td>{e(section)}</td><td>{e(r['images'].replace('-img01', ''))}</td>"
        f"<td><select data-i='{i}' data-f='scope_status'>{scope}</select></td>"
        f"<td><select data-i='{i}' data-f='standard_code'>{codes}</select></td>"
        f"<td><input data-i='{i}' data-f='nutrient_form_code' value='{e(r['nutrient_form_code'])}' size='12'></td>"
        f"<td class='note'>{e(r['note'])}</td></tr>"
    )


_PAGE = """<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><title>名稱對照表確認</title>
<style>
:root { --line:#ddd; }
body { margin:0 16px 40px; font:14px/1.5 system-ui, "Microsoft JhengHei", sans-serif; background:#fff; color:#222; }
header { position:sticky; top:0; background:#f4f6f8; border-bottom:1px solid var(--line); padding:8px 0; display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
table { border-collapse:collapse; width:100%; margin-bottom:16px; }
td, th { border:1px solid var(--line); padding:3px 6px; vertical-align:top; word-break:break-all; }
td.note { color:#666; font-size:13px; }
tr.changed { background:#fff8e0; }
</style></head><body>
<header><strong>名稱對照表確認</strong>
<span>範圍內＝要評估的 13 項營養素或 3 項允許成分；成分欄裡營養素的原料（例如檸檬酸鈣）一律範圍外（D45）</span>
<button id="export">匯出 name_map.csv</button></header>
{{BODY}}
<script>
const DATA = {{DATA}};
const KEY = "name-review:" + location.pathname;
let edits = {};
try { edits = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
document.querySelectorAll("[data-i]").forEach(el => {
  const k = el.dataset.i + "|" + el.dataset.f;
  if (k in edits) { el.value = edits[k]; el.closest("tr").classList.add("changed"); }
  el.oninput = el.onchange = () => {
    edits[k] = el.value; el.closest("tr").classList.add("changed");
    try { localStorage.setItem(KEY, JSON.stringify(edits)); } catch (e) {}
  };
});
document.getElementById("export").onclick = () => {
  const rows = DATA.rows.map((r, i) => {
    const out = { ...r };
    for (const f of ["scope_status", "standard_code", "nutrient_form_code"]) if ((i + "|" + f) in edits) out[f] = edits[i + "|" + f];
    return out;
  });
  const q = v => /[",\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  const text = "\\ufeff" + [DATA.fields, ...rows.map(r => DATA.fields.map(f => r[f] ?? ""))].map(r => r.map(v => q(String(v))).join(",")).join("\\r\\n") + "\\r\\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type:"text/csv" })); a.download = "name_map.csv"; a.click();
};
</script></body></html>
"""
