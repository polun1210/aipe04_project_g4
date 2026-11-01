import urllib.error

import pytest

from app.rag.embedder import EmbeddingError, OpenRouterEmbedder, embedder_from_env


def test_missing_embedding_model_is_an_error(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        embedder_from_env()


def test_blank_embedding_model_is_an_error(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "  ")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        embedder_from_env()


def test_missing_api_key_is_an_error(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "m")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        embedder_from_env()


def test_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "vendor/model-x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert embedder_from_env().model == "vendor/model-x"


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", {}, None)  # type: ignore[arg-type]


def test_vectors_are_returned_in_input_order():
    def transport(body, timeout):
        assert body == {"model": "m", "input": ["a", "b"]}
        return {"data": [{"index": 1, "embedding": [2, 2]}, {"index": 0, "embedding": [1, 1]}]}

    assert OpenRouterEmbedder("m", "k", transport).embed(["a", "b"]) == [[1.0, 1.0], [2.0, 2.0]]


def test_rate_limit_is_retried_then_succeeds():
    calls = []
    sleeps = []

    def transport(body, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise _http_error(429)
        return {"data": [{"index": 0, "embedding": [1]}]}

    embedder = OpenRouterEmbedder("m", "k", transport, sleep=sleeps.append)
    assert embedder.embed(["a"]) == [[1.0]]
    assert sleeps == [1.0, 2.0]


def test_client_error_is_not_retried():
    calls = []

    def transport(body, timeout):
        calls.append(1)
        raise _http_error(400)

    with pytest.raises(EmbeddingError):
        OpenRouterEmbedder("m", "k", transport, sleep=lambda s: None).embed(["a"])
    assert len(calls) == 1


def test_wrong_count_is_an_error():
    def transport(body, timeout):
        return {"data": [{"index": 0, "embedding": [1]}]}

    with pytest.raises(EmbeddingError, match="不符"):
        OpenRouterEmbedder("m", "k", transport).embed(["a", "b"])
