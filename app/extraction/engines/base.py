"""引擎替換點：每個引擎都轉成同一種中間結果，後續流程不知道是哪個引擎（spec「引擎與轉接層」）。"""

from typing import Protocol

from pydantic import Field

from app.extraction.types import ImageInput
from app.schemas.common import BoundingBox, StrictModel


class TextBlock(StrictModel):
    """引擎讀出的一段文字。座標系 ＝ 依 EXIF 方向轉正後的圖（D15）。"""

    text: str
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class EngineResult(StrictModel):
    image_id: str
    engine_version: str  # 寫進 extraction_meta.ocr_version
    blocks: list[TextBlock]


class Engine(Protocol):
    def run(self, image: ImageInput) -> EngineResult: ...
