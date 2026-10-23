"""敘述層的 LLM 呼叫（工單 6）：判定層結論 → 白話文字。

LLM 只負責「把已經定好的結論講白話」，不判斷、不算數字；輸出一律要過 narration_check。
用環境變數 NARRATOR 明確切換：
  - template（預設）：不呼叫 LLM，報告直接用固定模板
  - openrouter：經 OpenRouter 呼叫 NARRATOR_MODEL（服務商 NARRATOR_PROVIDER），金鑰沿用 OPENROUTER_API_KEY
型號與服務商都必填、沒有預設值，理由同辨識模組：預設型號可能被悄悄換掉，結果就無法追溯。
"""

import json
import os
import urllib.error
from functools import lru_cache
from http.client import HTTPException
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from app.extraction.engines.openrouter import Route, Transport, _strict, http_transport
from app.schemas.enums import IngredientCode, NarrationKind
from app.schemas.narration import NarrationInput, NarrationOutput

PROMPT_VERSION = "narration-v1"  # 改提示詞或輸出結構就要加版本
TEMPERATURE = 0.2  # 措辭可以不同，但隨機程度調低
TIMEOUT_SECONDS = 30

PROMPT = """你是幫長輩解釋「用藥與保健食品檢查結果」的助理。下面的 JSON 是程式已經判定好的結論，你只負責把它講成白話，不可以自己判斷或計算。

規則：
1. 每一條 interactions 都要剛好寫一則 kind=interaction 的說明，ingredient_code 照抄；不能漏、不能多。
2. relevant_nutrients 裡有 ul（上限比對）的營養素，可以寫一則 kind=nutrient 的說明；沒有 ul 的不用寫。
3. 剛好寫一則 kind=summary（ingredient_code 為 null），用一兩句話講這次最需要先注意什麼。
4. 只能用 JSON 裡出現過的數字；百分比用 ul.ratio × 100 四捨五入到整數。不要寫任何劑量建議。
5. 建議只能是這三種之一：錯開服用時間、告知醫師或藥師、併用前先和醫師或藥師討論。
   不可以叫人停藥、減量、改吃別的產品。
6. 不可以出現「安全」「可放心」「無問題」「沒有交互作用」「不會超標」「確診」這類保證的字眼。
7. 等級不是 priority 的提醒，不要用「立即」「緊急」「危險」「嚴重」這類強烈字眼。
8. user_has_supplement 為 false 的提醒，要說明使用者沒有補充這個成分，是因為服用的藥物而提醒。
9. 句子簡短，用台灣繁體中文，稱呼使用者為「你」。

成分中文名稱：{names}

判定層結論：
{assessment}
"""


class NarratorError(Exception):
    """LLM 呼叫失敗或回傳格式不對；呼叫端會重試，最後改用固定模板。"""


class Narrator(Protocol):
    def narrate(self, request: NarrationInput, names: dict[IngredientCode, str]) -> NarrationOutput: ...


class _LlmItem(BaseModel):
    kind: NarrationKind
    ingredient_code: IngredientCode | None
    text: str


class _LlmNarration(BaseModel):
    items: list[_LlmItem]


def _response_schema() -> dict[str, Any]:
    schema = _LlmNarration.model_json_schema()
    return _strict(schema, schema.get("$defs", {}))


class OpenRouterNarrator:
    def __init__(self, transport: Transport, route: Route) -> None:
        self._send = transport
        self.route = route

    def narrate(self, request: NarrationInput, names: dict[IngredientCode, str]) -> NarrationOutput:
        prompt = PROMPT.format(
            names=json.dumps({k.value: v for k, v in names.items()}, ensure_ascii=False),
            assessment=request.assessment.model_dump_json(exclude={"case_id"}),
        )
        try:
            response = self._send(self._body(prompt), TIMEOUT_SECONDS)
        except (OSError, HTTPException, ValueError, urllib.error.URLError) as e:
            raise NarratorError(f"呼叫 OpenRouter 失敗：{e}") from e
        return self._parse(response)

    def _body(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.route.model,
            "temperature": TEMPERATURE,
            "provider": {"only": [self.route.provider], "allow_fallbacks": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "narration", "strict": True, "schema": _response_schema()},
            },
            "messages": [{"role": "user", "content": prompt}],
        }

    def _parse(self, response: dict[str, Any]) -> NarrationOutput:
        try:
            text = response["choices"][0]["message"]["content"]
            parsed = _LlmNarration.model_validate_json(text)
            return NarrationOutput(
                items=[i.model_dump() for i in parsed.items],
                model=self.route.model,
                prompt_version=PROMPT_VERSION,
            )
        except (KeyError, IndexError, TypeError, ValidationError) as e:
            raise NarratorError(f"OpenRouter 回應格式錯誤：{e}") from e


@lru_cache(maxsize=1)
def get_narrator() -> Narrator | None:
    """None ＝ 不呼叫 LLM，報告用固定模板。"""
    mode = os.environ.get("NARRATOR", "template")
    if mode == "template":
        return None
    if mode != "openrouter":
        raise ValueError(f"NARRATOR 只能是 template 或 openrouter，收到 {mode!r}")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model, provider = os.environ.get("NARRATOR_MODEL"), os.environ.get("NARRATOR_PROVIDER")
    if not api_key or not model or not provider:
        raise ValueError("NARRATOR=openrouter 時，OPENROUTER_API_KEY、NARRATOR_MODEL、NARRATOR_PROVIDER 都必須設定")
    return OpenRouterNarrator(http_transport(api_key), Route(model, provider))
