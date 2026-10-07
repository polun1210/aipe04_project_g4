"""引擎替換點：每個引擎都轉成同一種中間結果，後續流程不知道是哪個引擎（spec「引擎與轉接層」）。"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import Field

from app.extraction.types import ImageInput
from app.schemas.common import BoundingBox, StrictModel
from app.schemas.enums import LabelSection


class TextBlock(StrictModel):
    """引擎讀出的一段文字。座標系 ＝ 依 EXIF 方向轉正後的圖（D15）。"""

    text: str
    bbox: BoundingBox | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


# ── 直接讀出結構的引擎（Gemini）才有的結果 ─────────────────────────
# D11：只放原文、數值、單位、區塊。單位保留標示原文（「毫克」「μg」），
# 名稱標準化與單位對映都由規則層做，兩條路線才能公平比較。


class ReadingRow(StrictModel):
    """引擎讀出的一列標示成分，尚未經規則層整理。"""

    raw_text: str  # 整列原文，例如「檸檬酸鈣(含純鈣50mg) 238毫克 24%」
    raw_name: str  # 名稱原文，含括號內容，不得修改
    amount: float | None = Field(default=None, ge=0)  # 每份含量數值；讀不到為 null
    unit_raw: str | None = None  # 單位原文
    percent_dv: float | None = Field(default=None, ge=0)  # 每日參考值%，不是劑量
    label_section: LabelSection
    bbox: BoundingBox | None = None


class ServingReading(StrictModel):
    """「每一份量」那一行。"""

    raw_text: str
    serving_size: float | None = Field(default=None, gt=0)  # 劑型單位數，不是重量
    dose_unit_raw: str | None = None  # 劑型原文，例如「粒」「錠」
    bbox: BoundingBox | None = None


class LabelReading(StrictModel):
    serving: ServingReading | None = None  # 標示上找不到「每一份量」就是 null
    rows: list[ReadingRow] = Field(default_factory=list)
    suggested_intake_raw: str | None = None  # 建議吃法原文，例如「每日1次，每次2粒」
    headings: list[str] = Field(default_factory=list)  # 區塊標題原文，例如「營養標示」「成分」


class EngineResult(StrictModel):
    image_id: str
    engine_version: str  # 寫進 extraction_meta.ocr_version
    blocks: list[TextBlock]
    # 只有直接讀出結構的引擎才填；OCR 引擎（Cloud Vision）為 null，由規則層從 blocks 整理
    reading: LabelReading | None = None


class EngineRecording(StrictModel):
    """一次真實呼叫的原始紀錄（D14）。轉換函式只吃這個，因此換轉換規則時不必重新呼叫付費服務。"""

    image_id: str
    engine: str  # cloud_vision、gemini
    request: dict[str, Any]  # 呼叫參數（模型、設定、提示詞版本），不含金鑰與圖片內容
    response: dict[str, Any]  # 服務回傳的原始 JSON
    image_width: int = Field(gt=0)  # 轉正後送出那張圖的尺寸，位置框以它為準
    image_height: int = Field(gt=0)
    latency_ms: float = Field(ge=0)
    recorded_at: datetime


class Engine(Protocol):
    def run(self, image: ImageInput) -> EngineResult: ...
