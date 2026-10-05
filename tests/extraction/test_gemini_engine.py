"""Gemini 轉接器：用假的錄製回應測轉換結果，不需要金鑰與網路。"""

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from google.genai import errors, types
from PIL import Image

from app.extraction import ExtractionError, ImageInput, ReplayEngine, extract
from app.extraction.engines.base import EngineRecording
from app.extraction.engines.gemini import GeminiEngine, to_engine_result
from app.schemas.common import BoundingBox
from app.schemas.enums import LabelSection
from app.schemas.label import ExtractionDraft


class FakeModels:
    def __init__(self, response: dict | None, error: Exception | None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self.error:
            raise self.error
        return types.GenerateContentResponse.model_validate(self.response)


def fake_client(response: dict | None = None, error: Exception | None = None):
    return SimpleNamespace(models=FakeModels(response, error))


@pytest.fixture
def table(load_recording) -> EngineRecording:
    return load_recording("gemini", "nutrition_table")


# ── 轉換：只放原文、數值、單位、區塊（D11）─────────────────────────


def test_每列保留名稱原文含括號內容(table):
    rows = to_engine_result(table).reading.rows
    assert [r.raw_name for r in rows] == ["維生素D", "檸檬酸鈣(含純鈣50mg)", "紅麴"]


def test_數值與單位原文分開保留且不換算(table):
    row = to_engine_result(table).reading.rows[0]
    assert (row.amount, row.unit_raw) == (10, "微克")


def test_每日參考值百分比和含量分開(table):
    row = to_engine_result(table).reading.rows[0]
    assert (row.amount, row.percent_dv) == (10, 100)


def test_每列記錄出自哪個區塊(table):
    sections = [r.label_section for r in to_engine_result(table).reading.rows]
    assert sections == [LabelSection.NUTRITION_TABLE, LabelSection.NUTRITION_TABLE, LabelSection.INGREDIENT_LIST]


def test_成分欄沒寫含量的列數值留空(table):
    red_yeast = to_engine_result(table).reading.rows[2]
    assert (red_yeast.amount, red_yeast.unit_raw) == (None, None)


def test_不產生標準代碼與範圍狀態(table):
    dumped = to_engine_result(table).model_dump_json()
    assert "standard_code" not in dumped
    assert "scope_status" not in dumped


def test_讀出每一份量的劑型單位數與劑型原文(table):
    serving = to_engine_result(table).reading.serving
    assert (serving.serving_size, serving.dose_unit_raw) == (2, "粒")


def test_標示上沒有每一份量時留空(load_recording):
    assert to_engine_result(load_recording("gemini", "ingredient_list_only")).reading.serving is None


def test_保留建議吃法原文(table):
    assert to_engine_result(table).reading.suggested_intake_raw == "每日1次，每次2粒"


def test_正規化座標換算成轉正後圖片的像素框(table):
    # box_2d [200, 50, 240, 700]，圖 800×1000 → x 40–560、y 200–240
    assert to_engine_result(table).reading.rows[0].bbox == BoundingBox(x=40, y=200, width=520, height=40)


def test_座標上下顛倒時當作沒有框(table):
    assert to_engine_result(table).reading.rows[1].bbox is None  # box_2d [300, 600, 280, 700]


def test_讀到的原文也攤成文字區塊供關鍵字檢查(table):
    texts = [b.text for b in to_engine_result(table).blocks]
    assert {"營養標示", "每一份量 2 粒", "紅麴"} <= set(texts)


def test_引擎版本記錄模型版本與提示詞版本(table):
    assert to_engine_result(table).engine_version == "gemini/gemini-2.5-flash/prompt-g1"


def test_結構化輸出不符格式時拋出辨識錯誤(load_recording):
    with pytest.raises(ExtractionError, match="結構化輸出"):
        to_engine_result(load_recording("gemini", "schema_mismatch"))


def test_沒有回傳內容時拋出辨識錯誤並附上原因(load_recording):
    with pytest.raises(ExtractionError, match="SAFETY"):
        to_engine_result(load_recording("gemini", "blocked"))


def test_拿到別的引擎的紀錄時拋出辨識錯誤(load_recording):
    with pytest.raises(ExtractionError):
        to_engine_result(load_recording("cloud_vision", "nutrition_table"))


# ── 呼叫：送出前轉正、請求內容 ─────────────────────────────────────


def test_送出的圖已依EXIF方向轉正(table, rotated_photo):
    client = fake_client(table.response)
    rec = GeminiEngine(client, model="gemini-test").record(ImageInput(image_id="p01-img01", content=rotated_photo))
    image_part = client.models.calls[0]["contents"][0]
    assert Image.open(BytesIO(image_part.inline_data.data)).size == (20, 40)
    assert (rec.image_width, rec.image_height) == (20, 40)


def test_請求使用結構化輸出且溫度為零(table, make_jpeg):
    client = fake_client(table.response)
    GeminiEngine(client, model="gemini-test").record(ImageInput(image_id="p01-img01", content=make_jpeg(30, 50)))
    config = client.models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
    assert config.temperature == 0


def test_紀錄載明模型與提示詞版本(table, make_jpeg):
    rec = GeminiEngine(fake_client(table.response), model="gemini-test").record(
        ImageInput(image_id="p01-img01", content=make_jpeg(30, 50))
    )
    assert rec.request == {"model": "gemini-test", "prompt_version": "g1", "temperature": 0.0}


def test_錄下的原始回應轉換後與直接執行結果相同(table, make_jpeg):
    engine = GeminiEngine(fake_client(table.response), model="gemini-test")
    image = ImageInput(image_id="p01-img01", content=make_jpeg(800, 1000))
    assert to_engine_result(engine.record(image)) == engine.run(image)


def test_呼叫失敗時拋出辨識錯誤(make_jpeg):
    error = errors.ClientError(403, {"error": {"code": 403, "message": "API key not valid", "status": "PERMISSION_DENIED"}})
    with pytest.raises(ExtractionError, match="Gemini"):
        GeminiEngine(fake_client(error=error), model="gemini-test").run(ImageInput(image_id="p01-img01", content=make_jpeg(30, 50)))


def test_沒有設定金鑰時拋出辨識錯誤(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ExtractionError, match="GEMINI_API_KEY"):
        GeminiEngine.from_env()


# ── 和重播引擎、辨識函式接得起來 ───────────────────────────────────


def test_轉換結果可存成錄製檔交給辨識函式重播(table, tmp_path):
    result = to_engine_result(table)
    (tmp_path / "p01-img01.json").write_text(result.model_dump_json(), encoding="utf-8")
    draft = extract(
        UUID("b2000000-0000-4000-8000-000000000002"),
        [ImageInput(image_id="p01-img01", content=b"fake")],
        engine=ReplayEngine(tmp_path),
    )
    ExtractionDraft.model_validate(draft.model_dump())
    assert draft.extraction_meta.ocr_version == "gemini/gemini-2.5-flash/prompt-g1"


def test_沒有指定模型時不使用預設值而是報錯(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    with pytest.raises(ExtractionError, match="GEMINI_MODEL"):
        GeminiEngine.from_env()

