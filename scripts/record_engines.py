"""錄製引擎回應（D14）：對每張照片真的呼叫一次引擎，把原始回應與轉換後的 EngineResult 存成 JSON。

**會呼叫付費服務**（在免費額度內），由使用者手動執行；pytest 只讀錄好的檔案。

    uv run python scripts/record_engines.py --engine cloud_vision --images data/images \
        --out tests/fixtures/engine_responses/cloud_vision/

輸出：
    <out>/<image_id>.json      EngineResult，ReplayEngine 直接讀這個
    <out>/raw/<image_id>.json  EngineRecording（原始回應、呼叫參數、延遲、轉正後尺寸）

已經錄過的照片預設跳過，避免重複花費；要重錄加 --force。
轉換規則改了但不想重新呼叫服務時，用 --reconvert 從 raw/ 重新產生 EngineResult。
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 `python scripts/...` 找得到 app

from dotenv import load_dotenv  # noqa: E402

from app.extraction.engines.base import EngineRecording, EngineResult  # noqa: E402
from app.extraction.types import ExtractionError, ImageInput  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
ENGINES = ("cloud_vision", "gemini")


class Recorder:
    """record：真的呼叫服務；convert：把原始紀錄轉成 EngineResult。"""

    def __init__(
        self,
        record: Callable[[ImageInput], EngineRecording],
        convert: Callable[[EngineRecording], EngineResult],
    ) -> None:
        self.record = record
        self.convert = convert


def recorder_for(engine: str) -> Recorder:
    """依名稱建立真實引擎。在這裡才 import，只做 --reconvert 時不需要金鑰。"""
    if engine == "cloud_vision":
        from app.extraction.engines import cloud_vision as module

        real = module.CloudVisionEngine.from_env()
    else:
        from app.extraction.engines import gemini as module

        real = module.GeminiEngine.from_env()
    return Recorder(real.record, module.to_engine_result)


def converter_for(engine: str) -> Callable[[EngineRecording], EngineResult]:
    if engine == "cloud_vision":
        from app.extraction.engines.cloud_vision import to_engine_result
    else:
        from app.extraction.engines.gemini import to_engine_result
    return to_engine_result


def find_images(images_dir: Path, only: list[str] | None) -> list[Path]:
    paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if only:
        wanted = set(only)
        paths = [p for p in paths if p.stem in wanted]
    return paths


def write_json(path: Path, model: EngineRecording | EngineResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def record_all(recorder: Recorder, images: list[Path], out: Path, force: bool) -> list[str]:
    """回傳失敗的照片編號。一張失敗不影響其他張。"""
    failed = []
    for path in images:
        image_id = path.stem  # 檔名即照片編號（D15）
        raw_path = out / "raw" / f"{image_id}.json"
        if raw_path.exists() and not force:
            print(f"跳過 {image_id}（已錄過；要重錄加 --force）")
            continue
        try:
            recording = recorder.record(ImageInput(image_id=image_id, content=path.read_bytes()))
        except ExtractionError as e:
            print(f"失敗 {image_id}：{e}", file=sys.stderr)
            failed.append(image_id)
            continue
        write_json(raw_path, recording)  # 先存原始回應：之後轉換失敗也不必重新付費
        if not convert_one(recorder.convert, recording, out):
            failed.append(image_id)
            continue
        print(f"完成 {image_id}（{recording.latency_ms:.0f} ms）")
    return failed


def reconvert_all(convert: Callable[[EngineRecording], EngineResult], out: Path, only: list[str] | None) -> list[str]:
    failed = []
    for raw_path in sorted((out / "raw").glob("*.json")):
        if only and raw_path.stem not in only:
            continue
        recording = EngineRecording.model_validate_json(raw_path.read_text(encoding="utf-8"))
        if convert_one(convert, recording, out):
            print(f"重新轉換 {recording.image_id}")
        else:
            failed.append(recording.image_id)
    return failed


def convert_one(convert: Callable[[EngineRecording], EngineResult], recording: EngineRecording, out: Path) -> bool:
    try:
        result = convert(recording)
    except ExtractionError as e:
        print(f"轉換失敗 {recording.image_id}：{e}（原始回應已保存在 raw/）", file=sys.stderr)
        return False
    write_json(out / f"{recording.image_id}.json", result)
    return True


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="錄製引擎原始回應（會呼叫付費服務）")
    parser.add_argument("--engine", required=True, choices=ENGINES)
    parser.add_argument("--images", type=Path, default=Path("data/images"), help="照片資料夾，檔名即照片編號")
    parser.add_argument("--out", type=Path, required=True, help="例如 tests/fixtures/engine_responses/cloud_vision/")
    parser.add_argument("--only", nargs="+", metavar="IMAGE_ID", help="只處理這幾張")
    parser.add_argument("--force", action="store_true", help="已錄過的也重新呼叫服務")
    parser.add_argument("--reconvert", action="store_true", help="不呼叫服務，只從 raw/ 重新轉換")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, recorder: Recorder | None = None) -> int:
    args = parse_args(argv)
    if args.reconvert:
        convert = recorder.convert if recorder else converter_for(args.engine)
        failed = reconvert_all(convert, args.out, args.only)
    else:
        if not args.images.is_dir():
            print(f"找不到照片資料夾 {args.images}", file=sys.stderr)
            return 2
        images = find_images(args.images, args.only)
        if not images:
            print(f"{args.images} 裡沒有照片（支援 {', '.join(sorted(IMAGE_SUFFIXES))}）", file=sys.stderr)
            return 2
        if recorder is None:
            load_dotenv()
            try:
                recorder = recorder_for(args.engine)
            except ExtractionError as e:
                print(e, file=sys.stderr)
                return 2
        failed = record_all(recorder, images, args.out, args.force)
    if failed:
        print(f"{len(failed)} 張失敗：{', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
