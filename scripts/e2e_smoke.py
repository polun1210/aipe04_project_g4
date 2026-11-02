"""全系統串接驗證：同一組輸入走完整流程，並比對 memory+csv 與 pg+pg 兩種設定的結果是否一致。

用法（pg 版需要先 alembic upgrade head、import_catalog，並設 DATABASE_URL）：
    uv run python scripts/e2e_smoke.py              # 兩種設定都跑，並比對
    uv run python scripts/e2e_smoke.py --only pg    # 只跑 pg 版（STORE=pg CATALOG_SOURCE=pg）
    uv run python scripts/e2e_smoke.py --only memory

每種設定在獨立的子行程執行（環境變數要在載入 app 之前設好）。
AUTH=test、EXTRACTOR=stub、NARRATOR=template：不需要任何金鑰。
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "schemas" / "examples"

CONFIGS = {
    "memory": {"STORE": "memory", "CATALOG_SOURCE": "csv"},
    "pg": {"STORE": "pg", "CATALOG_SOURCE": "pg"},
}
FIXED_ENV = {"AUTH": "test", "EXTRACTOR": "stub", "NARRATOR": "template"}

PROFILE = {
    "birth_year": 1954,
    "birth_month": 3,
    "sex": "male",
    "conditions": {"selected": ["hypertension", "dyslipidemia"], "none_selected": False},
}

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TIME_SUFFIX = "_at"
_RESULT_MARK = "\n@@RESULT@@"


class StepFailed(Exception):
    pass


def _png() -> bytes:
    """最小的合法 1x1 PNG（stub 辨識不讀圖，但上傳端會檢查是不是圖片）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\xff\xff\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixel) + chunk(b"IEND", b"")


def _step(name: str, response, expected: tuple[int, ...]):
    ok = response.status_code in expected
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}: HTTP {response.status_code}", flush=True)
    if not ok:
        raise StepFailed(f"{name}：預期 {expected}，收到 {response.status_code}：{response.text[:500]}")
    return response.json() if response.content else None


def _run_flow() -> dict:
    """在目前行程的環境變數設定下，走完整流程，回傳各步驟的重點結果。"""
    from fastapi.testclient import TestClient

    from app.main import create_app

    png = _png()
    submission = json.loads((EXAMPLES / "05a_verification_submission.json").read_text(encoding="utf-8"))
    out: dict = {}
    with TestClient(create_app()) as client:
        _step("健康檢查 GET /api/health", client.get("/api/health"), (200,))
        _step("登入者 GET /api/me", client.get("/api/me"), (200,))
        out["profile"] = _step("儲存健康資料 PUT /api/me/profile", client.put("/api/me/profile", json=PROFILE), (200,))

        drug_draft = _step(
            "上傳藥包 POST /api/drug-drafts",
            client.post("/api/drug-drafts", files=[("images", ("drug.png", png, "image/png"))]),
            (201,),
        )
        rows = drug_draft["rows"]
        out["drug_draft_row_count"] = len(rows)

        # 校對：沿用草稿每一列的名稱，再自行新增一列
        selected = [
            {"draft_id": drug_draft["draft_id"], "row_id": r["row_id"], "name": r["raw_name"]} for r in rows
        ]
        selected.append({"draft_id": None, "row_id": None, "name": "氧化鎂錠", "dose_mg": 250, "times_per_day": 2})
        lookup = _step(
            "藥名對照 GET /api/drugs/lookup", client.get("/api/drugs/lookup", params={"name": "立普妥"}), (200,)
        )
        out["lookup"] = lookup

        product_ids = []
        expected_names: dict[str, list[str]] = {"out_of_scope": [], "unresolved": []}
        for category in ("綜合維他命", "魚油"):
            files = [
                ("ingredient_images", ("i.png", png, "image/png")),
                ("nutrition_images", ("n.png", png, "image/png")),
            ]
            draft = _step(
                f"上傳保健食品 POST /api/supplement-drafts（{category}）",
                client.post("/api/supplement-drafts", files=files, data={"category": category}),
                (201,),
            )
            body = {**submission, "draft_product_id": draft["product_id"]}
            names = {r["row_id"]: r["raw_name"] for r in draft["nutrients"]}
            for n in submission["nutrients"]:
                if n["scope_status"] in expected_names and names.get(n["row_id"]):
                    expected_names[n["scope_status"]].append(names[n["row_id"]])
            created = _step(f"校對送出 POST /api/products（{category}）", client.post("/api/products", json=body), (201,))
            product_ids.append(created["product_id"])

        request = {"drugs": {"selected": selected, "none_selected": False}, "product_ids": product_ids}
        assessment = _step("產生評估 POST /api/assessments", client.post("/api/assessments", json=request), (200, 201))
        out["assessment"] = assessment
        case_id = assessment["case_id"]

        report = _step("產生報告 POST /api/assessments/{id}/report", client.post(f"/api/assessments/{case_id}/report"), (201,))
        out["report"] = report
        _check_ingredient_disclosures(report["disclosures"], expected_names)
        again = _step("重複產生報告（應回同一份）", client.post(f"/api/assessments/{case_id}/report"), (200,))
        if again["report_id"] != report["report_id"]:
            raise StepFailed("重複產生報告：report_id 不一致")

        listed = _step("報告記錄 GET /api/reports", client.get("/api/reports"), (200,))
        if report["report_id"] not in [r["report_id"] for r in listed]:
            raise StepFailed("報告記錄：找不到剛產生的報告")
        fetched = _step("單份報告 GET /api/reports/{id}", client.get(f"/api/reports/{report['report_id']}"), (200,))
        if fetched != report:
            raise StepFailed("單份報告：內容和產生時不一致（凍結失敗）")
    return out


def _check_ingredient_disclosures(disclosures: dict, expected: dict[str, list[str]]) -> None:
    """校對時選了「無法確認」「不在評估範圍」的成分，報告揭露必須列出原文名稱。"""
    for status, field in (("out_of_scope", "out_of_scope_ingredients"), ("unresolved", "unresolved_ingredients")):
        want = list(dict.fromkeys(expected[status]))
        if not want:
            raise StepFailed(f"揭露檢查：測試資料裡沒有 {status} 的成分，檢查失效")
        if disclosures[field] != want:
            raise StepFailed(f"揭露 {field}：預期 {want}，實際 {disclosures[field]}")
    print("  [OK ] 報告揭露列出無法確認與不在範圍的成分", flush=True)


def _normalize(value, seen: dict[str, str]):
    """把隨機產生的 UUID 依出現順序換成代號、去掉時間欄位，才能比對兩次執行。"""
    if isinstance(value, dict):
        return {k: _normalize(v, seen) for k, v in value.items() if not k.endswith(_TIME_SUFFIX)}
    if isinstance(value, list):
        return [_normalize(v, seen) for v in value]
    if isinstance(value, str):
        return _UUID.sub(lambda m: seen.setdefault(m.group(0), f"<uuid{len(seen)}>"), value)
    return value


def _diff(a, b, path: str = "$") -> list[str]:
    if type(a) is not type(b):
        return [f"{path}: 型別不同 {type(a).__name__} vs {type(b).__name__}"]
    if isinstance(a, dict):
        diffs = [f"{path}.{k}: 只在其中一邊" for k in a.keys() ^ b.keys()]
        for k in a.keys() & b.keys():
            diffs += _diff(a[k], b[k], f"{path}.{k}")
        return diffs
    if isinstance(a, list):
        if len(a) != len(b):
            return [f"{path}: 長度不同 {len(a)} vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {a!r} vs {b!r}"]


def _worker(name: str) -> None:
    os.environ.update(FIXED_ENV | CONFIGS[name])
    sys.path.insert(0, str(ROOT))  # 直接執行 scripts/ 下的檔案時，專案根目錄不在 sys.path
    result = _run_flow()
    sys.stdout.write(_RESULT_MARK + json.dumps(result, ensure_ascii=False))


def _spawn(name: str) -> dict:
    print(f"== 設定 {name}：{CONFIGS[name]} ==", flush=True)
    proc = subprocess.run(
        [sys.executable, __file__, "--worker", name],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    head, _, payload = proc.stdout.partition(_RESULT_MARK)
    print(head, end="")
    if proc.returncode != 0 or not payload:
        print(proc.stderr[-2000:])
        raise StepFailed(f"設定 {name} 沒有跑完")
    return json.loads(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=list(CONFIGS))
    parser.add_argument("--worker", choices=list(CONFIGS), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        _worker(args.worker)
        return 0
    names = [args.only] if args.only else list(CONFIGS)
    if "pg" in names and not os.environ.get("DATABASE_URL"):
        print("pg 版需要設定 DATABASE_URL", file=sys.stderr)
        return 2
    try:
        results = {n: _spawn(n) for n in names}
    except StepFailed as e:
        print(f"\n失敗：{e}")
        return 1
    if len(names) == 2:
        norm = {n: _normalize(r, {}) for n, r in results.items()}
        diffs = _diff(norm["memory"], norm["pg"])
        print(f"\n== 比對 memory+csv 與 pg+pg：{'一致' if not diffs else f'{len(diffs)} 處不一致'} ==")
        for d in diffs[:50]:
            print("  差異", d)
        if diffs:
            return 1
    print("\n全部步驟通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
