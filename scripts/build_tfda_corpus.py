"""從 nutrition-agent 的 TFDA 仿單挑出代表仿單，存到 data/sources/tfda/。

用法：uv run python scripts/build_tfda_corpus.py --source C:/Project/nutrition-agent

規則（ADR-0013）：
- 排除只有「目前無仿單資料」的空檔
- 只取 g4 `drug_items` 有的有效成分；每個有效成分只取日期最新的一份（日期相同取許可證字號較大者）
- 移除 base64 圖片（原檔約 98% 是圖片）；NUL 換成替代字元「�」，看得出此處缺字
- 存成 data/sources/tfda/<有效成分代碼>/<許可證字號>.md，檔頭註明許可證字號、原始檔名、抓取日期
- 語料在建置時固定：之後不再連外部資料庫，要更新就重跑這支腳本

只讀來源專案，不改它。輸出固定排序、固定換行（LF），重跑後 git diff 應為空。
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

from app.catalog_source import CsvCatalogSource
from app.rag.chunking import NUL, REPLACEMENT_CHAR, strip_base64_images

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sources" / "tfda"
TFDA_FILE = re.compile(r"^(?P<license>.+)_(?P<date>\d{8})\.md$")
# nutrition-agent 的資料夾名稱與 g4 代碼拼法不同的少數例子
FOLDER_ALIASES = {"aluminium_hydroxide": "aluminum_hydroxide"}
NO_LABEL_STUB = "目前無仿單資料"
SIZE_TARGET_BYTES = 10 * 1024 * 1024


def folder_code(folder_name: str) -> str:
    """`Glucosamine hydrochloride` → glucosamine_hydrochloride。"""
    code = re.sub(r"[\s\-]+", "_", folder_name.strip().lower())
    return FOLDER_ALIASES.get(code, code)


def pick_latest(root: Path, codes: set[str]) -> tuple[dict[str, tuple[tuple[str, str], Path]], list[str]]:
    latest: dict[str, tuple[tuple[str, str], Path]] = {}
    unmatched: set[str] = set()
    for path in sorted(root.rglob("*.md")):
        match = TFDA_FILE.match(path.name)
        if match is None or path.parent == root:
            continue  # 檔名帶 _01 序號的不符合格式，不收
        code = folder_code(path.parent.name)
        if code not in codes:
            unmatched.add(path.parent.name)
            continue
        if NO_LABEL_STUB in path.read_text(encoding="utf-8"):
            continue  # 轉檔結果只有「目前無仿單資料」的空檔，不算仿單
        key = (match["date"], match["license"])
        if code not in latest or key > latest[code][0]:
            latest[code] = (key, path)
    return latest, sorted(unmatched)


def render(code: str, source: Path) -> str:
    match = TFDA_FILE.match(source.name)
    assert match is not None
    fetched = datetime.strptime(match["date"], "%Y%m%d").date().isoformat()
    header = (
        "<!-- 來源：TFDA 藥品仿單（衛生福利部食品藥物管理署）\n"
        f"許可證字號：{match['license']}\n"
        f"原始檔名：{source.name}\n"
        f"抓取日期：{fetched}\n"
        f"有效成分：{code}\n"
        "處理：已移除內嵌圖片，內文照原檔 -->\n\n"
    )
    body = strip_base64_images(source.read_text(encoding="utf-8").replace(NUL, REPLACEMENT_CHAR))
    return header + body.lstrip("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="nutrition-agent 專案根目錄")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    root = args.source / "knowledge" / "raw" / "tfda"
    codes = {item.active_ingredient_code for item in CsvCatalogSource().load().drug_items}
    latest, unmatched = pick_latest(root, codes)

    total = 0
    for code in sorted(latest):
        (_, source) = latest[code]
        target = OUT / code / f"{TFDA_FILE.match(source.name)['license']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = render(code, source)
        target.write_bytes(text.encode("utf-8").replace(b"\r\n", b"\n"))
        total += target.stat().st_size
        print(f"{code}: {target.name}（{target.stat().st_size / 1024:.0f} KB）")

    missing = sorted(codes - set(latest))
    print(f"\n共 {len(latest)} 份，合計 {total / 1024 / 1024:.2f} MB（目標 {SIZE_TARGET_BYTES // 1024 // 1024} MB 內）")
    print(f"drug_items 沒有仿單的成分：{', '.join(missing) or '無'}")
    print(f"來源有但不在 drug_items 的資料夾（略過）：{', '.join(unmatched) or '無'}")
    return 0 if total <= SIZE_TARGET_BYTES else 1


if __name__ == "__main__":
    sys.exit(main())
