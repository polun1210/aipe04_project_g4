"""Cloud Vision 轉接器：用假的錄製回應測轉換結果，不需要金鑰與網路。"""

import json
from io import BytesIO
from uuid import UUID

import pytest
from google.api_core.exceptions import PermissionDenied
from google.cloud import vision
from PIL import Image

from app.extraction import ExtractionError, ImageInput, ReplayEngine, extract
from app.extraction.engines.base import EngineRecording
from app.extraction.engines.cloud_vision import CloudVisionEngine, to_engine_result
from app.schemas.common import BoundingBox
from app.schemas.enums import QualityStatus
from app.schemas.label import ExtractionDraft, SourceImage


class FakeVisionClient:
    """記下收到的請求，回傳一份錄製好的回應。"""

    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error
        self.requests: list = []

    def batch_annotate_images(self, *, requests):
        self.requests.extend(requests)
        if self.error:
            raise self.error
        resp = vision.AnnotateImageResponse.from_json(json.dumps(self.response))
        return vision.BatchAnnotateImagesResponse(responses=[resp])


@pytest.fixture
def table(load_recording) -> EngineRecording:
    return load_recording("cloud_vision", "nutrition_table")


def texts(recording: EngineRecording) -> list[str]:
    return [b.text for b in to_engine_result(recording).blocks]


# ── 轉換：字詞框組成一行一個 TextBlock ─────────────────────────────


def test_每行文字組成一個區塊且依序排列(table):
    assert texts(table) == ["營養標示", "每一份量 2 粒", "維生素D 10微克", "鈣"]


def test_只在服務標示空白的位置補空白(table):
    # 「維生素」與「D」之間沒有空白標記 → 直接相連；「D」後面有 → 補一個空白
    assert "維生素D 10微克" in texts(table)


def test_行框是該行所有字詞框的聯集(table):
    line = to_engine_result(table).blocks[2]
    assert line.bbox == BoundingBox(x=60, y=200, width=440, height=30)


def test_一行的信心分數取最不確定的字詞(table):
    line = to_engine_result(table).blocks[1]  # 每一份量 0.98、2 0.97、粒 0.95
    assert line.confidence == pytest.approx(0.95)


def test_超出圖外的框裁到圖內(table):
    corner = to_engine_result(table).blocks[3]  # 原框從 (-5, -3) 開始
    assert corner.bbox == BoundingBox(x=0, y=0, width=30, height=30)


def test_沒有文字的回應得到空的區塊清單(table):
    empty = table.model_copy(update={"response": {}})
    assert to_engine_result(empty).blocks == []


def test_引擎版本記錄功能與模型(table):
    assert to_engine_result(table).engine_version == "cloud_vision/document_text_detection/builtin/stable"


def test_不產生結構化讀取結果(table):
    assert to_engine_result(table).reading is None


def test_服務回報錯誤時拋出辨識錯誤(load_recording):
    with pytest.raises(ExtractionError, match="Bad image data"):
        to_engine_result(load_recording("cloud_vision", "error"))


def test_回應格式和真實服務不符時拋出辨識錯誤(table):
    broken = table.model_copy(update={"response": {"fullTextAnnotation": {"pagez": []}}})
    with pytest.raises(ExtractionError, match="格式錯誤"):
        to_engine_result(broken)


def test_拿到別的引擎的紀錄時拋出辨識錯誤(load_recording):
    with pytest.raises(ExtractionError):
        to_engine_result(load_recording("gemini", "nutrition_table"))


# ── 呼叫：送出前轉正、請求內容 ─────────────────────────────────────


def test_送出的圖已依EXIF方向轉正(table, rotated_photo):
    client = FakeVisionClient(table.response)
    CloudVisionEngine(client).record(ImageInput(image_id="p01-img01", content=rotated_photo))
    sent = Image.open(BytesIO(client.requests[0].image.content))
    assert sent.size == (20, 40)


def test_紀錄的圖片尺寸是轉正後的尺寸(table, rotated_photo):
    rec = CloudVisionEngine(FakeVisionClient(table.response)).record(
        ImageInput(image_id="p01-img01", content=rotated_photo)
    )
    assert (rec.image_width, rec.image_height) == (20, 40)


def test_方向已正確的圖原檔照送(table, make_jpeg):
    original = make_jpeg(30, 50)
    client = FakeVisionClient(table.response)
    CloudVisionEngine(client).record(ImageInput(image_id="p01-img01", content=original))
    assert client.requests[0].image.content == original


def test_請求使用文件文字偵測與指定模型(table, make_jpeg):
    client = FakeVisionClient(table.response)
    CloudVisionEngine(client, model="builtin/latest").record(ImageInput(image_id="p01-img01", content=make_jpeg(30, 50)))
    feature = client.requests[0].features[0]
    assert feature.type_ is vision.Feature.Type.DOCUMENT_TEXT_DETECTION
    assert feature.model == "builtin/latest"


def test_錄下的原始回應轉換後與直接執行結果相同(table, make_jpeg):
    engine = CloudVisionEngine(FakeVisionClient(table.response))
    image = ImageInput(image_id="p01-img01", content=make_jpeg(800, 1000))
    assert to_engine_result(engine.record(image)) == engine.run(image)


def test_呼叫失敗時拋出辨識錯誤(make_jpeg):
    engine = CloudVisionEngine(FakeVisionClient(error=PermissionDenied("金鑰無效")))
    with pytest.raises(ExtractionError, match="Cloud Vision"):
        engine.run(ImageInput(image_id="p01-img01", content=make_jpeg(30, 50)))


def test_不是圖片的檔案拋出辨識錯誤(table):
    engine = CloudVisionEngine(FakeVisionClient(table.response))
    with pytest.raises(ExtractionError, match="不是可讀取的圖片"):
        engine.run(ImageInput(image_id="p01-img01", content=b"not an image"))


# ── 和重播引擎、辨識函式接得起來 ───────────────────────────────────


def test_轉換結果可存成錄製檔交給辨識函式重播(table, tmp_path):
    result = to_engine_result(table)
    (tmp_path / "p01-img01.json").write_text(result.model_dump_json(), encoding="utf-8")
    draft = extract(
        UUID("b2000000-0000-4000-8000-000000000002"),
        [ImageInput(image_id="p01-img01", content=b"fake")],
        [SourceImage(image_id="p01-img01", quality_status=QualityStatus.ACCEPTED)],
        engine=ReplayEngine(tmp_path),
    )
    ExtractionDraft.model_validate(draft.model_dump())
    assert draft.extraction_meta.ocr_version == result.engine_version
