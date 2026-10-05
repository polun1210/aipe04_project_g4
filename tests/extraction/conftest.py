"""辨識模組測試共用的 fixture。照片一律在測試中即時產生，repo 不放照片。"""

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.extraction.engines.base import EngineRecording

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_recording() -> Callable[[str, str], EngineRecording]:
    """讀自己構造的假錄製回應（格式同真實服務回應，見 tests/extraction/fixtures/）。"""

    def load(engine: str, name: str) -> EngineRecording:
        path = FIXTURES / engine / f"{name}.json"
        return EngineRecording.model_validate_json(path.read_text(encoding="utf-8"))

    return load


def _jpeg(width: int, height: int, orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    buf = BytesIO()
    if orientation is None:
        img.save(buf, format="JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


@pytest.fixture
def make_jpeg() -> Callable[..., bytes]:
    """產生一張 JPEG；orientation 給值時寫入 EXIF 方向標記。"""
    return _jpeg


@pytest.fixture
def rotated_photo() -> bytes:
    """像素是 40×20（橫），EXIF 方向 6（需順時針轉 90 度），轉正後應是 20×40（直）。"""
    return _jpeg(40, 20, orientation=6)
