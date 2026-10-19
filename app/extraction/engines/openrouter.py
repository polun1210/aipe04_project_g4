"""OpenRouter 轉接器（VLM 主路線：Gemini 3.8 Flash）。

經 OpenRouter 的 OpenAI 相容 Chat Completions API 呼叫，提示詞與輸出結構沿用 Gemini 轉接器：
只讀出每一列的原文、數值、單位原文與區塊；標準代碼、範圍狀態與單位對映一律由後續程式處理。

- 用原生結構化輸出（response_format = json_schema）；回傳後仍用 Pydantic 驗證
- **指定服務商、不准自動換**：同一個型號在不同服務商的正確率可能差很多，
  所以請求裡固定 provider.only 與 allow_fallbacks = false，只由指定的服務商處理
- **數值容錯**：經 OpenRouter 時結構檢查比原生寬鬆，數值欄位偶爾會收到文字（例如「11±2.0」）。
  收到文字就取第一個數字，並把該列標成需要使用者確認，不讓整張照片失敗
- **備援**：主型號遇到 408／429／5xx 或逾時，若有設定備援型號就改呼叫備援；其他錯誤（例如 400）不換

金鑰：OPENROUTER_API_KEY。型號與服務商都必填、沒有預設值（預設型號可能過時或被悄悄換到新版，
結果就無法追溯）：OPENROUTER_MODEL、OPENROUTER_PROVIDER；備援為選填，兩個要一起設：
OPENROUTER_FALLBACK_MODEL、OPENROUTER_FALLBACK_PROVIDER。
"""

import base64
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from app.extraction.engines.base import EngineRecording, EngineResult
from app.extraction.engines.gemini import PROMPT, _blocks, _GeminiLabel, _to_reading
from app.extraction.engines.image_io import load_upright
from app.extraction.types import ExtractionError, ImageInput

ENGINE_NAME = "openrouter"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_VERSION = "g1"  # 與 Gemini 共用提示詞；改提示詞或結構就要加版本，engine_version 會跟著變
TEMPERATURE = 0.0
# 使用者同步等待，整體上限約 60 秒：每次呼叫 28 秒，主型號逾時改呼叫備援最多再 28 秒；多張照片由 extract() 同時處理
TIMEOUT_SECONDS = 28
# 長邊超過就先縮小再送：比較集實測（97%）的照片長邊約 2400 像素；手機原圖約 4000 像素，送原圖只會更慢
MAX_SIDE = 2400
_RETRYABLE_STATUS = {408, 429}  # 加上所有 5xx

# (請求內容) → 服務回傳的 JSON。HTTP 錯誤以 urllib.error.HTTPError 拋出。測試換成假的，不真的連網
Transport = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class Route:
    model: str  # 完整型號，例如 google/gemini-3.8-flash
    provider: str  # OpenRouter 的服務商代號，例如 google-ai-studio


def http_transport(api_key: str) -> Transport:
    def send(body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.load(response)

    return send


def _strict(schema: Any, defs: dict[str, Any]) -> Any:
    """把 Pydantic 的 JSON Schema 攤平（展開 $ref），每個物件都不允許多餘欄位、所有欄位都必填。"""
    if isinstance(schema, list):
        return [_strict(s, defs) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return _strict(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    out = {k: _strict(v, defs) for k, v in schema.items() if k not in ("$defs", "title")}
    if out.get("type") == "object":
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}))
    return out


def _response_schema(model: type[BaseModel] = _GeminiLabel) -> dict[str, Any]:
    schema = model.model_json_schema()
    return _strict(schema, schema.get("$defs", {}))


class OpenRouterEngine:
    # 子類別換掉這四項就能讀別種文件（例如藥包），呼叫、備援、逾時、縮圖都共用
    engine_name = ENGINE_NAME
    prompt = PROMPT
    prompt_version = PROMPT_VERSION
    output_model: type[BaseModel] = _GeminiLabel

    def __init__(self, transport: Transport, primary: Route, fallback: Route | None = None) -> None:
        self._send = transport
        self.primary = primary
        self.fallback = fallback

    @classmethod
    def from_env(cls) -> "OpenRouterEngine":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ExtractionError("沒有設定環境變數 OPENROUTER_API_KEY")
        model, provider = os.environ.get("OPENROUTER_MODEL"), os.environ.get("OPENROUTER_PROVIDER")
        if not model or not provider:
            raise ExtractionError("OPENROUTER_MODEL 與 OPENROUTER_PROVIDER 都必須明確指定")
        fb_model = os.environ.get("OPENROUTER_FALLBACK_MODEL")
        fb_provider = os.environ.get("OPENROUTER_FALLBACK_PROVIDER")
        if bool(fb_model) != bool(fb_provider):
            raise ExtractionError("OPENROUTER_FALLBACK_MODEL 與 OPENROUTER_FALLBACK_PROVIDER 要一起設定")
        fallback = Route(fb_model, fb_provider) if fb_model and fb_provider else None
        return cls(http_transport(api_key), Route(model, provider), fallback)

    def _body(self, route: Route, data_url: str) -> dict[str, Any]:
        return {
            "model": route.model,
            "temperature": TEMPERATURE,
            "provider": {"only": [route.provider], "allow_fallbacks": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "reading", "strict": True, "schema": _response_schema(self.output_model)},
            },
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": self.prompt},
                    ],
                }
            ],
        }

    def record(self, image: ImageInput) -> EngineRecording:
        """真的呼叫一次 OpenRouter（必要時改呼叫備援），回傳原始紀錄（不含金鑰與圖片內容）。"""
        upright = load_upright(image.content, image.image_id, max_side=MAX_SIDE)
        data_url = f"data:{upright.mime_type};base64," + base64.b64encode(upright.content).decode("ascii")

        started = perf_counter()
        route, primary_error = self.primary, None
        try:
            response = self._send(self._body(route, data_url))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if self.fallback is None or not _retryable(e):
                raise ExtractionError(f"{image.image_id} 呼叫 OpenRouter 失敗：{e}") from e
            route, primary_error = self.fallback, _describe(e)
            try:
                response = self._send(self._body(route, data_url))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e2:
                raise ExtractionError(f"{image.image_id} 主型號與備援都失敗：{primary_error}；{e2}") from e2
        latency_ms = (perf_counter() - started) * 1000

        request: dict[str, Any] = {
            "model": route.model,
            "provider": route.provider,
            "prompt_version": self.prompt_version,
            "temperature": TEMPERATURE,
        }
        if primary_error is not None:
            request["fallback_from"] = {"model": self.primary.model, "error": primary_error}
        return EngineRecording(
            image_id=image.image_id,
            engine=self.engine_name,
            request=request,
            response=response,
            image_width=upright.width,
            image_height=upright.height,
            latency_ms=latency_ms,
            recorded_at=datetime.now(timezone.utc),
        )

    def run(self, image: ImageInput) -> EngineResult:
        return to_engine_result(self.record(image))


def _retryable(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in _RETRYABLE_STATUS or error.code >= 500
    return isinstance(error, (urllib.error.URLError, TimeoutError))


def _describe(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code}"
    return type(error).__name__


_FIRST_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


def _as_number(value: Any) -> tuple[Any, bool]:
    """數值欄位收到文字時取第一個數字。回傳（值, 是否經過容錯）。

    取不到數字、或取到負數（含量不可能是負的，不能把負號拿掉當正數用）就給 null，同樣要人確認。
    """
    if not isinstance(value, str):
        return value, False
    match = _FIRST_NUMBER.search(value.replace(",", ""))
    number = float(match.group()) if match else None
    return (number if number is not None and number >= 0 else None), True


def to_engine_result(recording: EngineRecording) -> EngineResult:
    """把錄下的 OpenRouter 原始回應轉成 EngineResult。不連網，測試與重新轉換都用它。"""
    image_id = recording.image_id
    if recording.engine != ENGINE_NAME:
        raise ExtractionError(f"{image_id} 的紀錄不是 OpenRouter 的：{recording.engine}")
    try:
        choice = recording.response["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ExtractionError(f"{image_id} 的 OpenRouter 回應格式錯誤") from e
    if not text:
        raise ExtractionError(f"{image_id} OpenRouter 沒有回傳內容（finish_reason={choice.get('finish_reason')}）")

    try:
        raw = json.loads(text)
        tolerated_rows: set[int] = set()
        for i, row in enumerate(raw.get("rows") or []):
            for key in ("amount", "percent_dv"):
                row[key], changed = _as_number(row.get(key))
                if changed:
                    tolerated_rows.add(i)
        serving_tolerated = False
        if isinstance(raw.get("serving"), dict):
            raw["serving"]["serving_size"], serving_tolerated = _as_number(raw["serving"].get("serving_size"))
        reading = _to_reading(_GeminiLabel.model_validate(raw), recording.image_width, recording.image_height)
    except (json.JSONDecodeError, AttributeError, TypeError, ValidationError) as e:
        raise ExtractionError(f"{image_id} 的 OpenRouter 輸出不符合格式") from e

    rows = [r.model_copy(update={"needs_review": True}) if i in tolerated_rows else r for i, r in enumerate(reading.rows)]
    serving = reading.serving
    if serving is not None and serving_tolerated:
        serving = serving.model_copy(update={"needs_review": True})
    reading = reading.model_copy(update={"rows": rows, "serving": serving})

    model_version = recording.response.get("model") or recording.request["model"]
    return EngineResult(
        image_id=image_id,
        engine_version=(
            f"{ENGINE_NAME}/{model_version}/{recording.request['provider']}/prompt-{recording.request['prompt_version']}"
        ),
        blocks=_blocks(reading),
        reading=reading,
    )
