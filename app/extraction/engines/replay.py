"""重播引擎：讀取錄製的原始回應，測試不呼叫任何真實服務。"""

from pathlib import Path

from pydantic import ValidationError

from app.extraction.engines.base import EngineResult
from app.extraction.types import ExtractionError, ImageInput


class ReplayEngine:
    """從 `<recordings_dir>/<image_id>.json` 讀出 EngineResult。"""

    def __init__(self, recordings_dir: Path) -> None:
        self.recordings_dir = Path(recordings_dir)

    def run(self, image: ImageInput) -> EngineResult:
        path = self.recordings_dir / f"{image.image_id}.json"
        try:
            return EngineResult.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise ExtractionError(f"找不到 {image.image_id} 的錄製回應：{path}") from e
        except ValidationError as e:
            raise ExtractionError(f"{image.image_id} 的錄製回應格式錯誤") from e
