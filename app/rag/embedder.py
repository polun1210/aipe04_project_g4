"""文字 → 向量。正式實作走 OpenRouter 的 /embeddings，金鑰沿用 OPENROUTER_API_KEY。

型號由 EMBEDDING_MODEL 指定，必填、沒有預設值：型號被悄悄換掉，向量就不能和舊的混用，結果也無法追溯
（理由同 NARRATOR_MODEL，見 ADR-0011）。型號會跟著每個切塊存進 evidence.chunks.embedding_model。
"""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

API_URL = "https://openrouter.ai/api/v1/embeddings"
TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 5
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

# (請求內容, 最多等幾秒) → 服務回傳的 JSON。測試換成假的，不真的連網
Transport = Callable[[dict[str, Any], float], dict[str, Any]]


class EmbeddingError(Exception):
    """embedding 呼叫失敗或回傳格式不對。"""


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenRouterEmbedder:
    def __init__(
        self,
        model: str,
        api_key: str,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self._transport = transport or _http_transport(api_key)
        self._sleep = sleep

    def embed(self, texts: list[str]) -> list[list[float]]:
        body = {"model": self.model, "input": texts}
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._transport(body, TIMEOUT_SECONDS)
                break
            except urllib.error.HTTPError as e:
                if e.code not in _RETRYABLE_STATUS or attempt == MAX_ATTEMPTS - 1:
                    raise EmbeddingError(f"embedding 失敗：HTTP {e.code}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == MAX_ATTEMPTS - 1:
                    raise EmbeddingError(f"embedding 連線失敗：{e}") from e
            self._sleep(float(2**attempt))  # 被限速或服務暫時錯誤：等 1、2、4、8 秒再試
        try:
            rows = sorted(response["data"], key=lambda row: row["index"])
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as e:
            raise EmbeddingError("embedding 回傳格式不對") from e
        if len(vectors) != len(texts):
            raise EmbeddingError(f"embedding 數量 {len(vectors)} 與輸入數量 {len(texts)} 不符")
        return vectors


def _http_transport(api_key: str) -> Transport:
    def send(body: dict[str, Any], timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    return send


def embedder_from_env() -> OpenRouterEmbedder:
    """EMBEDDING_MODEL 與 OPENROUTER_API_KEY 都要設，缺了就報錯，不會退回預設值。"""
    model = os.environ.get("EMBEDDING_MODEL", "").strip()
    if not model:
        raise RuntimeError("請設定 EMBEDDING_MODEL（完整型號，例如 qwen/qwen3-embedding-8b）；沒有預設值，見 ADR-0013")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("請設定 OPENROUTER_API_KEY")
    return OpenRouterEmbedder(model, api_key)
