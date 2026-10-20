"""影像品質檢查：用程式畫出像標示的「文字」圖，再做出模糊、縮小、過曝、白斑、變暗的版本。"""

from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from app.extraction import ImageInput, check_quality
from app.extraction.quality import assess
from app.schemas.enums import QualityStatus, RejectReason


def _label(width=1200, height=1600) -> np.ndarray:
    """白底黑字、一行一行的假標示（灰階）。"""
    img = Image.new("L", (width, height), 235)
    draw = ImageDraw.Draw(img)
    rng = np.random.default_rng(0)
    for y in range(40, height - 40, 28):
        x = 40
        while x < width - 80:
            w = int(rng.integers(12, 60))
            draw.rectangle([x, y, x + w, y + 14], fill=20)
            x += w + int(rng.integers(8, 20))
    return np.asarray(img)


def _jpeg(gray: np.ndarray) -> bytes:
    buf = BytesIO()
    Image.fromarray(np.clip(gray, 0, 255).astype(np.uint8)).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def test_清楚的標示通過():
    assert assess(_jpeg(_label())) is None


def test_長條形但字清楚的網路圖通過():
    assert assess(_jpeg(_label(1500, 260))) is None


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda g: cv2.GaussianBlur(g, (0, 0), 6), RejectReason.BLUR),
        (lambda g: cv2.resize(g, (300, 400)), RejectReason.LOW_RESOLUTION),
        (lambda g: g.astype(int) + 240, RejectReason.GLARE),
        (lambda g: g * 0.3, RejectReason.LOW_LIGHT),
    ],
    ids=["模糊", "太小", "過曝", "太暗"],
)
def test_壞照片以應有的原因被拒(make, reason):
    assert assess(_jpeg(make(_label()))) is reason


def test_暗照片角落有一盞燈仍算太暗而不是模糊():
    g = _label() * 0.3
    h, w = g.shape
    g[: h // 10, : w // 10] = 255
    assert assess(_jpeg(g)) is RejectReason.LOW_LIGHT


def test_照片中間一塊白斑算反光():
    g = _label().copy()
    h, w = g.shape
    g[h // 4 : h // 4 + int(h * 0.4), w // 4 : w // 4 + int(w * 0.4)] = 255
    assert assess(_jpeg(g)) is RejectReason.GLARE


def test_讀不出的檔案不通過():
    assert assess(b"not an image") is RejectReason.UNSUPPORTED_LABEL


def test_每張照片各自判定():
    images = [ImageInput(image_id="a", content=_jpeg(_label())), ImageInput(image_id="b", content=b"x")]
    a, b = check_quality(images)
    assert (a.quality_status, b.quality_status, b.reject_reason) == (
        QualityStatus.ACCEPTED,
        QualityStatus.REJECTED,
        RejectReason.UNSUPPORTED_LABEL,
    )
