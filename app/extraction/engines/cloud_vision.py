"""Cloud Vision 轉接器（路線 A 的前半段，issue 04）。

呼叫 document text detection，把字詞框依 Cloud Vision 回報的換行組成「一行一個 TextBlock」。
這一層只轉格式、不判斷內容：哪一行是成分名稱、哪個數字是每份含量，由之後的規則層處理。

金鑰：環境變數 GOOGLE_CLOUD_VISION_API_KEY；沒設時改用 Google 預設憑證
（GOOGLE_APPLICATION_CREDENTIALS 指向的服務帳戶 JSON）。
"""

import json
import os
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Protocol

from google.api_core.exceptions import GoogleAPIError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import vision

from app.extraction.engines.base import EngineRecording, EngineResult, TextBlock
from app.extraction.engines.image_io import load_upright
from app.extraction.types import ExtractionError, ImageInput
from app.schemas.common import BoundingBox

ENGINE_NAME = "cloud_vision"
DEFAULT_MODEL = "builtin/stable"  # 明確指定，避免 Google 改預設模型時結果悄悄改變
LANGUAGE_HINTS = ["zh-Hant", "en"]

_Break = vision.TextAnnotation.DetectedBreak.BreakType
_LINE_END = {_Break.EOL_SURE_SPACE, _Break.LINE_BREAK, _Break.HYPHEN}  # HYPHEN 是行尾斷字，不在原文中
_SPACE = {_Break.SPACE, _Break.SURE_SPACE}


class _VisionClient(Protocol):
    def batch_annotate_images(self, *, requests: list[Any]) -> Any: ...


class CloudVisionEngine:
    def __init__(self, client: _VisionClient, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self.model = model

    @classmethod
    def from_env(cls) -> "CloudVisionEngine":
        api_key = os.environ.get("GOOGLE_CLOUD_VISION_API_KEY")
        options = {"api_key": api_key} if api_key else None
        try:
            client = vision.ImageAnnotatorClient(client_options=options)
        except DefaultCredentialsError as e:
            raise ExtractionError(
                "沒有 Cloud Vision 憑證：請設定 GOOGLE_CLOUD_VISION_API_KEY 或 GOOGLE_APPLICATION_CREDENTIALS"
            ) from e
        return cls(client, model=os.environ.get("CLOUD_VISION_MODEL") or DEFAULT_MODEL)

    def record(self, image: ImageInput) -> EngineRecording:
        """真的呼叫一次 Cloud Vision，回傳原始紀錄。"""
        upright = load_upright(image.content, image.image_id)
        request = vision.AnnotateImageRequest(
            image=vision.Image(content=upright.content),
            features=[vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION, model=self.model)],
            image_context=vision.ImageContext(language_hints=LANGUAGE_HINTS),
        )
        started = perf_counter()
        try:
            batch = self._client.batch_annotate_images(requests=[request])
        except GoogleAPIError as e:
            raise ExtractionError(f"{image.image_id} 呼叫 Cloud Vision 失敗：{e}") from e
        latency_ms = (perf_counter() - started) * 1000

        response = vision.AnnotateImageResponse.to_json(batch.responses[0], use_integers_for_enums=False)
        return EngineRecording(
            image_id=image.image_id,
            engine=ENGINE_NAME,
            request={
                "feature": "DOCUMENT_TEXT_DETECTION",
                "model": self.model,
                "language_hints": LANGUAGE_HINTS,
            },
            response=json.loads(response),
            image_width=upright.width,
            image_height=upright.height,
            latency_ms=latency_ms,
            recorded_at=datetime.now(timezone.utc),
        )

    def run(self, image: ImageInput) -> EngineResult:
        return to_engine_result(self.record(image))


def to_engine_result(recording: EngineRecording) -> EngineResult:
    """把錄下的 Cloud Vision 原始回應轉成 EngineResult。不連網，測試與重新轉換都用它。"""
    if recording.engine != ENGINE_NAME:
        raise ExtractionError(f"{recording.image_id} 的紀錄不是 Cloud Vision 的：{recording.engine}")
    try:
        # 不忽略未知欄位：格式和真實回應不符時直接報錯，而不是默默少讀
        response = vision.AnnotateImageResponse.from_json(json.dumps(recording.response))
    except Exception as e:  # protobuf 的 ParseError 沒有公開的共同父類別
        raise ExtractionError(f"{recording.image_id} 的 Cloud Vision 回應格式錯誤") from e
    if response.error.code:
        raise ExtractionError(f"{recording.image_id} Cloud Vision 回報錯誤：{response.error.message}")

    blocks = [
        _line_block(line, recording.image_width, recording.image_height)
        for page in response.full_text_annotation.pages
        for block in page.blocks
        for paragraph in block.paragraphs
        for line in _split_lines(paragraph.words)
    ]
    return EngineResult(
        image_id=recording.image_id,
        engine_version=f"{ENGINE_NAME}/document_text_detection/{recording.request['model']}",
        blocks=[b for b in blocks if b.text],
    )


def _split_lines(words: Any) -> list[list[Any]]:
    """依每個字詞最後一個字元的換行標記，把段落切成行。"""
    lines: list[list[Any]] = []
    current: list[Any] = []
    for word in words:
        current.append(word)
        if _break_after(word) in _LINE_END:
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def _break_after(word: Any) -> Any:
    return word.symbols[-1].property.detected_break.type_ if word.symbols else _Break.UNKNOWN


def _line_block(words: list[Any], width: int, height: int) -> TextBlock:
    text = ""
    for word in words:
        text += "".join(s.text for s in word.symbols)
        if _break_after(word) in _SPACE:
            text += " "
    return TextBlock(
        text=text.strip(),
        bbox=_union_bbox(words, width, height),
        # 一行的可信度取決於最不確定的字詞，取最小值；proto 是 float32，四捨五入去掉 0.9300000071 的尾巴
        confidence=round(min(w.confidence for w in words), 4),
    )


def _union_bbox(words: list[Any], width: int, height: int) -> BoundingBox | None:
    # proto3 省略值為 0 的座標；讀回來時會補成 0，符合 Cloud Vision 的原意
    xs = [v.x for w in words for v in w.bounding_box.vertices]
    ys = [v.y for w in words for v in w.bounding_box.vertices]
    if not xs:
        return None
    # 傾斜的框可能有一角超出圖外，裁到圖內
    x0, x1 = max(0, min(xs)), min(width, max(xs))
    y0, y1 = max(0, min(ys)), min(height, max(ys))
    if x1 <= x0 or y1 <= y0:
        return None
    return BoundingBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0)
