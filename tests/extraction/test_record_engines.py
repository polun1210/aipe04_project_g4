"""錄製腳本：用假的引擎跑對外入口 main()，不呼叫任何真實服務。"""

import pytest

from app.extraction import ExtractionError, ImageInput, ReplayEngine
from app.extraction.engines.base import EngineRecording
from app.extraction.engines.cloud_vision import to_engine_result
from scripts.record_engines import Recorder, main


class FakeRecorder(Recorder):
    """回傳錄好的 Cloud Vision 回應，照片編號換成實際那張；fail_on 裡的照片模擬呼叫失敗。"""

    def __init__(self, template: EngineRecording, fail_on: set[str] = frozenset()) -> None:
        super().__init__(self._record, to_engine_result)
        self.template = template
        self.fail_on = fail_on
        self.called: list[str] = []

    def _record(self, image: ImageInput) -> EngineRecording:
        self.called.append(image.image_id)
        if image.image_id in self.fail_on:
            raise ExtractionError("模擬逾時")
        return self.template.model_copy(update={"image_id": image.image_id})


@pytest.fixture
def images(tmp_path, make_jpeg):
    folder = tmp_path / "images"
    folder.mkdir()
    for image_id in ["p01-img01", "p02-img01"]:
        (folder / f"{image_id}.jpg").write_bytes(make_jpeg(30, 50))
    (folder / "readme.txt").write_text("不是照片", encoding="utf-8")
    return folder


@pytest.fixture
def recorder(load_recording):
    return FakeRecorder(load_recording("cloud_vision", "nutrition_table"))


def run(images, out, recorder, *extra):
    return main(["--engine", "cloud_vision", "--images", str(images), "--out", str(out), *extra], recorder=recorder)


def test_每張照片都存下原始紀錄與轉換結果(images, tmp_path, recorder):
    out = tmp_path / "out"
    assert run(images, out, recorder) == 0
    assert sorted(p.name for p in (out / "raw").glob("*.json")) == ["p01-img01.json", "p02-img01.json"]
    assert sorted(p.name for p in out.glob("*.json")) == ["p01-img01.json", "p02-img01.json"]


def test_檔名就是照片編號且非照片檔不處理(images, tmp_path, recorder):
    run(images, tmp_path / "out", recorder)
    assert recorder.called == ["p01-img01", "p02-img01"]


def test_轉換結果可直接給重播引擎讀(images, tmp_path, recorder):
    out = tmp_path / "out"
    run(images, out, recorder)
    result = ReplayEngine(out).run(ImageInput(image_id="p02-img01", content=b""))
    assert result.image_id == "p02-img01"
    assert result.blocks


def test_已錄過的照片預設不再呼叫服務(images, tmp_path, recorder):
    out = tmp_path / "out"
    run(images, out, recorder)
    recorder.called.clear()
    run(images, out, recorder)
    assert recorder.called == []


def test_加force會重新呼叫服務(images, tmp_path, recorder):
    out = tmp_path / "out"
    run(images, out, recorder)
    recorder.called.clear()
    run(images, out, recorder, "--force")
    assert recorder.called == ["p01-img01", "p02-img01"]


def test_只處理指定的照片(images, tmp_path, recorder):
    run(images, tmp_path / "out", recorder, "--only", "p02-img01")
    assert recorder.called == ["p02-img01"]


def test_一張失敗不影響其他張且結束碼非零(images, tmp_path, load_recording):
    recorder = FakeRecorder(load_recording("cloud_vision", "nutrition_table"), fail_on={"p01-img01"})
    out = tmp_path / "out"
    assert run(images, out, recorder) == 1
    assert (out / "p02-img01.json").exists()
    assert not (out / "raw" / "p01-img01.json").exists()


def test_轉換失敗時仍保留原始回應(images, tmp_path, load_recording):
    out = tmp_path / "out"
    assert run(images, out, FakeRecorder(load_recording("cloud_vision", "error"))) == 1
    assert (out / "raw" / "p01-img01.json").exists()
    assert not (out / "p01-img01.json").exists()


def test_重新轉換不呼叫服務(images, tmp_path, recorder):
    out = tmp_path / "out"
    run(images, out, recorder)
    (out / "p01-img01.json").unlink()
    recorder.called.clear()
    assert run(images, out, recorder, "--reconvert") == 0
    assert recorder.called == []
    assert (out / "p01-img01.json").exists()


def test_照片資料夾不存在時結束碼為2(tmp_path, recorder):
    assert run(tmp_path / "沒有這個資料夾", tmp_path / "out", recorder) == 2


def test_重新轉換失敗時不留下舊的轉換結果(tmp_path):
    from app.extraction.types import ExtractionError
    from scripts.record_engines import convert_one

    old = tmp_path / "p01-img01.json"
    old.write_text("{}", encoding="utf-8")

    def broken(recording):
        raise ExtractionError("格式錯誤")

    assert convert_one(broken, type("R", (), {"image_id": "p01-img01"})(), tmp_path) is False
    assert not old.exists()

