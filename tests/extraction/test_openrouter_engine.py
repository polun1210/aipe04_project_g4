"""OpenRouter 轉接器：用假的傳輸層測，不連網、不需要金鑰。"""

import json
import urllib.error
from uuid import UUID

import pytest

from app.extraction import ExtractionError, ImageInput, ReplayEngine, extract
from app.extraction.engines.openrouter import OpenRouterEngine, Route, to_engine_result
from app.schemas.enums import LabelSection, QualityStatus
from app.schemas.label import ExtractionDraft, SourceImage

PRIMARY = Route("google/gemini-3.8-flash", "google-ai-studio")
FALLBACK = Route("qwen/qwen3.8-flash", "alibaba")

LABEL = {
    "serving": {"raw_text": "每一份量 2 粒", "serving_size": 2, "dose_unit": "粒", "box_2d": [100, 50, 140, 400]},
    "rows": [
        {"raw_text": "鈣 200毫克 20%", "raw_name": "鈣", "amount": 200, "unit": "毫克", "percent_dv": 20,
         "label_section": "nutrition_table", "box_2d": [200, 50, 240, 600]},
        {"raw_text": "紅麴粉", "raw_name": "紅麴粉", "amount": None, "unit": None, "percent_dv": None,
         "label_section": "ingredient_list", "box_2d": None},
    ],
    "suggested_intake": "每日1次，每次2粒",
    "headings": ["營養標示", "成分"],
}  # fmt: skip


def reply(label=LABEL, model="google/gemini-3.8-flash"):
    content = label if isinstance(label, str) else json.dumps(label, ensure_ascii=False)
    return {"model": model, "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}


def http_error(code):
    return urllib.error.HTTPError("https://openrouter.ai", code, "error", {}, None)


class FakeTransport:
    """依序回應：每一項是 dict（回傳）或 Exception（拋出）。"""

    def __init__(self, *outcomes):
        self.outcomes, self.bodies = list(outcomes) or [reply()], []

    def __call__(self, body):
        self.bodies.append(body)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def record(transport, make_jpeg, fallback=None):
    return OpenRouterEngine(transport, PRIMARY, fallback).record(
        ImageInput(image_id="p01-img01", content=make_jpeg(100, 200))
    )


def test_讀出每一列的原文數值單位與區塊(make_jpeg):
    result = to_engine_result(record(FakeTransport(), make_jpeg))
    rows = result.reading.rows
    assert [(r.raw_name, r.amount, r.unit_raw, r.label_section) for r in rows] == [
        ("鈣", 200, "毫克", LabelSection.NUTRITION_TABLE),
        ("紅麴粉", None, None, LabelSection.INGREDIENT_LIST),
    ]
    assert not any(r.needs_review for r in rows)
    assert result.engine_version == "openrouter/google/gemini-3.8-flash/google-ai-studio/prompt-g1"


def test_請求固定服務商且不准自動換(make_jpeg):
    transport = FakeTransport()
    record(transport, make_jpeg)
    assert transport.bodies[0]["provider"] == {"only": ["google-ai-studio"], "allow_fallbacks": False}


def test_請求使用原生結構化輸出且結構不允許多餘欄位(make_jpeg):
    transport = FakeTransport()
    record(transport, make_jpeg)
    fmt = transport.bodies[0]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert "$defs" not in json.dumps(schema) and "$ref" not in json.dumps(schema)
    row = schema["properties"]["rows"]["items"]
    assert row["additionalProperties"] is False and set(row["required"]) == set(row["properties"])


def test_請求附上照片且錄製紀錄不含圖片與金鑰(make_jpeg):
    transport = FakeTransport()
    rec = record(transport, make_jpeg)
    body = transport.bodies[0]
    assert body["temperature"] == 0 and body["model"] == "google/gemini-3.8-flash"
    assert body["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert set(rec.request) == {"model", "provider", "prompt_version", "temperature"}


def test_數值欄位收到文字時取第一個數字並標成需要確認(make_jpeg):
    rows = [{**LABEL["rows"][0], "amount": "11±2.0", "percent_dv": 20}, LABEL["rows"][1]]
    result = to_engine_result(record(FakeTransport(reply({**LABEL, "rows": rows})), make_jpeg))
    first, second = result.reading.rows
    assert first.amount == 11 and first.needs_review
    assert not second.needs_review


@pytest.mark.parametrize(("text", "expected"), [(".5 mg", 0.5), ("1,000毫克", 1000), ("1e3", 1000), ("-2", None)])
def test_數值容錯正確處理小數點千分位指數與負號(make_jpeg, text, expected):
    rows = [{**LABEL["rows"][0], "amount": text}]
    row = to_engine_result(record(FakeTransport(reply({**LABEL, "rows": rows})), make_jpeg)).reading.rows[0]
    assert row.amount == expected and row.needs_review


def test_數值欄位的文字裡沒有數字時留空並標成需要確認(make_jpeg):
    rows = [{**LABEL["rows"][0], "amount": "微量"}]
    result = to_engine_result(record(FakeTransport(reply({**LABEL, "rows": rows})), make_jpeg))
    assert result.reading.rows[0].amount is None and result.reading.rows[0].needs_review


def test_每一份量收到文字時也容錯(make_jpeg):
    label = {**LABEL, "serving": {**LABEL["serving"], "serving_size": "2粒"}}
    serving = to_engine_result(record(FakeTransport(reply(label)), make_jpeg)).reading.serving
    assert serving.serving_size == 2 and serving.needs_review


def test_每一份量只寫重量時不當成粒數(make_jpeg):
    label = {**LABEL, "serving": {**LABEL["serving"], "raw_text": "每一份量0.8公克", "serving_size": 0.8, "dose_unit": "公克"}}
    assert to_engine_result(record(FakeTransport(reply(label)), make_jpeg)).reading.serving.serving_size is None


def test_輸出不符格式時拋出辨識錯誤(make_jpeg):
    with pytest.raises(ExtractionError, match="不符合格式"):
        to_engine_result(record(FakeTransport(reply('{"rows": "壞掉"}')), make_jpeg))


def test_輸出不是_JSON_時拋出辨識錯誤(make_jpeg):
    with pytest.raises(ExtractionError, match="不符合格式"):
        to_engine_result(record(FakeTransport(reply("這不是 JSON")), make_jpeg))


def test_沒有回傳內容時拋出辨識錯誤(make_jpeg):
    with pytest.raises(ExtractionError, match="沒有回傳內容"):
        to_engine_result(record(FakeTransport(reply("")), make_jpeg))


@pytest.mark.parametrize("error", [http_error(503), http_error(500), http_error(429), TimeoutError("逾時")])
def test_主型號暫時失敗時改呼叫備援並記錄原因(make_jpeg, error):
    transport = FakeTransport(error, reply(model="qwen/qwen3.8-flash"))
    rec = record(transport, make_jpeg, fallback=FALLBACK)
    assert [b["model"] for b in transport.bodies] == ["google/gemini-3.8-flash", "qwen/qwen3.8-flash"]
    assert transport.bodies[1]["provider"] == {"only": ["alibaba"], "allow_fallbacks": False}
    assert rec.request["model"] == "qwen/qwen3.8-flash" and rec.request["fallback_from"]["model"] == PRIMARY.model
    assert to_engine_result(rec).engine_version.startswith("openrouter/qwen/qwen3.8-flash/alibaba/")


def test_請求本身有錯時不改呼叫備援(make_jpeg):
    transport = FakeTransport(http_error(400), reply())
    with pytest.raises(ExtractionError, match="呼叫 OpenRouter 失敗"):
        record(transport, make_jpeg, fallback=FALLBACK)
    assert len(transport.bodies) == 1


def test_沒有設定備援時暫時失敗直接拋出辨識錯誤(make_jpeg):
    with pytest.raises(ExtractionError, match="呼叫 OpenRouter 失敗"):
        record(FakeTransport(http_error(503)), make_jpeg)


def test_主型號與備援都失敗時拋出辨識錯誤(make_jpeg):
    with pytest.raises(ExtractionError, match="主型號與備援都失敗"):
        record(FakeTransport(http_error(503), http_error(502)), make_jpeg, fallback=FALLBACK)


def test_沒有指定型號或服務商時不使用預設值而是報錯(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-3.8-flash")
    monkeypatch.delenv("OPENROUTER_PROVIDER", raising=False)
    with pytest.raises(ExtractionError, match="OPENROUTER_PROVIDER"):
        OpenRouterEngine.from_env()


def test_備援型號與服務商只設一個時報錯(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-3.8-flash")
    monkeypatch.setenv("OPENROUTER_PROVIDER", "google-ai-studio")
    monkeypatch.setenv("OPENROUTER_FALLBACK_MODEL", "qwen/qwen3.8-flash")
    monkeypatch.delenv("OPENROUTER_FALLBACK_PROVIDER", raising=False)
    with pytest.raises(ExtractionError, match="要一起設定"):
        OpenRouterEngine.from_env()


def test_轉換結果可存成錄製檔交給辨識函式重播(make_jpeg, tmp_path):
    result = to_engine_result(record(FakeTransport(), make_jpeg))
    (tmp_path / "p01-img01.json").write_text(result.model_dump_json(), encoding="utf-8")
    draft = extract(
        UUID("b2000000-0000-4000-8000-000000000002"),
        [ImageInput(image_id="p01-img01", content=b"fake")],
        [SourceImage(image_id="p01-img01", quality_status=QualityStatus.ACCEPTED)],
        engine=ReplayEngine(tmp_path),
    )
    ExtractionDraft.model_validate(draft.model_dump())
    assert draft.extraction_meta.ocr_version == "openrouter/google/gemini-3.8-flash/google-ai-studio/prompt-g1"
