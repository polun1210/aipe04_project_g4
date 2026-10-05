"""Gemini 轉接器（路線 B，issue 06）。

用結構化輸出（response schema）讓 Gemini 直接讀出每一列的原文、數值、單位與區塊（D11）。
**不要求 Gemini 做名稱標準化或單位換算**：標準代碼、範圍狀態、單位對映一律由規則層處理，
和 Cloud Vision 路線共用同一套程式，比較才公平。

位置框：要求 Gemini 給 box_2d（0–1000 正規化的 [ymin, xmin, ymax, xmax]），再換算成轉正後的
像素座標。VLM 的座標通常不可靠（D04），這裡照收，可不可用由 W1 比較表的「有框比例」與人工檢視判斷。

金鑰：環境變數 GEMINI_API_KEY；模型：GEMINI_MODEL（未設時用 DEFAULT_MODEL）。
"""

import os
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field, ValidationError

from app.extraction.engines.base import (
    EngineRecording,
    EngineResult,
    LabelReading,
    ReadingRow,
    ServingReading,
    TextBlock,
)
from app.extraction.engines.image_io import load_upright
from app.extraction.types import ExtractionError, ImageInput
from app.schemas.common import BoundingBox
from app.schemas.enums import LabelSection

ENGINE_NAME = "gemini"
DEFAULT_MODEL = "gemini-2.5-flash"
PROMPT_VERSION = "g1"  # 改提示詞或回應結構就要加版本，engine_version 會跟著變
TEMPERATURE = 0.0

PROMPT = """\
這是一張台灣保健食品包裝的照片。請只根據照片上看得到的文字，逐字照抄，填入指定的 JSON 結構。

規則：
1. 一律照抄原文，不翻譯、不改寫、不補字、不換算單位。看不清楚的數字填 null，不要猜。
2. rows：營養標示方框裡的每一列、每粒／每份含量說明裡的每一項、成分欄裡用頓號或逗號分開的每一項，各一列。
   - raw_name：名稱原文，括號與括號內的字一起照抄，例如「檸檬酸鈣(含純鈣50mg)」。
   - amount、unit：「每份」的含量數字與單位原文（例如 毫克、mg、微克、μg、IU）。
     同一列有「每份」與「每100公克」兩欄時，只填每份那一欄。成分欄沒寫含量就填 null。
   - percent_dv：每日參考值百分比的數字（不含 % 符號）。百分比絕對不可以填進 amount。
   - label_section：nutrition_table＝營養標示方框；per_unit_note＝每粒／每份含量說明小字；
     ingredient_list＝成分欄；front＝正面行銷文案；other＝其他。
   - raw_text：這一列在照片上的完整原文。
3. serving：「每一份量」那一行。serving_size 是劑型單位數（例如每份 2 粒就填 2），不是重量；
   dose_unit 是劑型原文（例如 粒、錠、顆、包、毫升）。照片上沒有「每一份量」就整個填 null。
4. suggested_intake：建議吃法的原文（例如「每日1次，每次2粒」），沒有就填 null。
5. headings：照片上出現的區塊標題原文，例如「營養標示」「成分」「注意事項」。
6. box_2d：該列在照片上的位置 [ymin, xmin, ymax, xmax]，以 0–1000 正規化；無法定位就填 null。
"""


# ── 送給 Gemini 的回應結構 ────────────────────────────────────────
# 用一般 BaseModel 而不是 StrictModel：Gemini 的 schema 不接受 additionalProperties。
# 每個欄位都不給預設值，Gemini 才會每個欄位都回（可為 null），不會自行省略。


class _GeminiRow(BaseModel):
    raw_text: str
    raw_name: str
    amount: float | None
    unit: str | None
    percent_dv: float | None
    label_section: LabelSection
    box_2d: list[int] | None = Field(description="[ymin, xmin, ymax, xmax]，0–1000 正規化")


class _GeminiServing(BaseModel):
    raw_text: str
    serving_size: float | None
    dose_unit: str | None
    box_2d: list[int] | None = Field(description="[ymin, xmin, ymax, xmax]，0–1000 正規化")


class _GeminiLabel(BaseModel):
    serving: _GeminiServing | None
    rows: list[_GeminiRow]
    suggested_intake: str | None
    headings: list[str]


class GeminiEngine:
    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "GeminiEngine":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ExtractionError("沒有設定環境變數 GEMINI_API_KEY")
        return cls(genai.Client(api_key=api_key), model=os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL)

    def record(self, image: ImageInput) -> EngineRecording:
        """真的呼叫一次 Gemini，回傳原始紀錄。"""
        upright = load_upright(image.content, image.image_id)
        config = types.GenerateContentConfig(
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            response_schema=_GeminiLabel,
        )
        started = perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=[types.Part.from_bytes(data=upright.content, mime_type=upright.mime_type), PROMPT],
                config=config,
            )
        except errors.APIError as e:
            raise ExtractionError(f"{image.image_id} 呼叫 Gemini 失敗：{e}") from e
        latency_ms = (perf_counter() - started) * 1000

        return EngineRecording(
            image_id=image.image_id,
            engine=ENGINE_NAME,
            request={"model": self.model, "prompt_version": PROMPT_VERSION, "temperature": TEMPERATURE},
            response=response.model_dump(
                mode="json",
                exclude_none=True,
                # HTTP 標頭與 SDK 自己解析的副本不屬於服務回應，不錄
                exclude={"sdk_http_response", "automatic_function_calling_history", "parsed"},
            ),
            image_width=upright.width,
            image_height=upright.height,
            latency_ms=latency_ms,
            recorded_at=datetime.now(timezone.utc),
        )

    def run(self, image: ImageInput) -> EngineResult:
        return to_engine_result(self.record(image))


def to_engine_result(recording: EngineRecording) -> EngineResult:
    """把錄下的 Gemini 原始回應轉成 EngineResult。不連網，測試與重新轉換都用它。"""
    image_id = recording.image_id
    if recording.engine != ENGINE_NAME:
        raise ExtractionError(f"{image_id} 的紀錄不是 Gemini 的：{recording.engine}")
    try:
        response = types.GenerateContentResponse.model_validate(recording.response)
    except ValidationError as e:
        raise ExtractionError(f"{image_id} 的 Gemini 回應格式錯誤") from e
    text = response.text
    if not text:
        finish = response.candidates[0].finish_reason if response.candidates else None
        raise ExtractionError(f"{image_id} Gemini 沒有回傳內容（finish_reason={finish}）")
    try:
        label = _GeminiLabel.model_validate_json(text)
        reading = _to_reading(label, recording.image_width, recording.image_height)
    except ValidationError as e:
        raise ExtractionError(f"{image_id} 的 Gemini 結構化輸出不符合格式") from e

    model_version = response.model_version or recording.request["model"]
    return EngineResult(
        image_id=image_id,
        engine_version=f"{ENGINE_NAME}/{model_version}/prompt-{recording.request['prompt_version']}",
        blocks=_blocks(reading),
        reading=reading,
    )


def _to_reading(label: _GeminiLabel, width: int, height: int) -> LabelReading:
    serving = None
    if label.serving is not None:
        serving = ServingReading(
            raw_text=label.serving.raw_text,
            serving_size=label.serving.serving_size,
            dose_unit_raw=label.serving.dose_unit,
            bbox=_to_bbox(label.serving.box_2d, width, height),
        )
    rows = [
        ReadingRow(
            raw_text=r.raw_text,
            raw_name=r.raw_name,
            amount=r.amount,
            unit_raw=r.unit,
            percent_dv=r.percent_dv,
            label_section=r.label_section,
            bbox=_to_bbox(r.box_2d, width, height),
        )
        for r in label.rows
    ]
    return LabelReading(
        serving=serving,
        rows=rows,
        suggested_intake_raw=label.suggested_intake,
        headings=label.headings,
    )


def _blocks(reading: LabelReading) -> list[TextBlock]:
    """把讀到的原文也攤成 TextBlock，讓「找關鍵字判斷是不是營養標示」這類檢查兩條路線通用。

    Gemini 不提供逐字信心分數，confidence 一律為 null。
    """
    blocks = [TextBlock(text=h) for h in reading.headings]
    if reading.serving is not None:
        blocks.append(TextBlock(text=reading.serving.raw_text, bbox=reading.serving.bbox))
    if reading.suggested_intake_raw:
        blocks.append(TextBlock(text=reading.suggested_intake_raw))
    blocks += [TextBlock(text=r.raw_text, bbox=r.bbox) for r in reading.rows]
    return [b for b in blocks if b.text]


def _to_bbox(box_2d: list[int] | None, width: int, height: int) -> BoundingBox | None:
    """[ymin, xmin, ymax, xmax]（0–1000）→ 轉正後圖片的像素框。格式不對就當作沒有框，不猜。"""
    if box_2d is None or len(box_2d) != 4:
        return None
    ymin, xmin, ymax, xmax = (min(max(v, 0), 1000) for v in box_2d)
    if xmax <= xmin or ymax <= ymin:
        return None
    x0, x1 = round(xmin * width / 1000), round(xmax * width / 1000)
    y0, y1 = round(ymin * height / 1000), round(ymax * height / 1000)
    return BoundingBox(x=x0, y=y0, width=max(1, x1 - x0), height=max(1, y1 - y0))
