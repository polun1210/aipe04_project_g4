"""送進引擎前的讀圖：依 EXIF 方向轉正（D15）。

手機照片常以「原始感光方向的像素 ＋ EXIF Orientation 標記」存檔。若直接把原檔交給引擎，
引擎回傳的座標可能是以未轉正的像素為準，前端畫框就會偏移。因此一律先在本機轉正，
把轉正後、已不含方向標記的圖送出；引擎回傳的座標自然就是轉正後的圖的座標。
"""

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.extraction.types import ExtractionError

_EXIF_ORIENTATION = 0x0112


@dataclass(frozen=True)
class UprightImage:
    content: bytes  # 實際送給引擎的檔案內容
    mime_type: str
    width: int
    height: int


def load_upright(content: bytes, image_id: str) -> UprightImage:
    """回傳轉正後的圖。方向本來就正確時原檔照送，避免重新壓縮損失畫質。"""
    try:
        img = Image.open(BytesIO(content))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ExtractionError(f"{image_id} 不是可讀取的圖片") from e

    orientation = img.getexif().get(_EXIF_ORIENTATION, 1)
    fmt = (img.format or "").upper()
    if orientation == 1 and fmt in {"JPEG", "PNG"}:
        return UprightImage(content, f"image/{fmt.lower()}", img.width, img.height)

    upright = ImageOps.exif_transpose(img)
    buf = BytesIO()
    if fmt == "PNG":
        upright.save(buf, format="PNG")
        mime = "image/png"
    else:
        # JPEG、HEIC 轉檔後等格式一律存成 JPEG；品質 95 讓小字不因壓縮而糊掉
        upright.convert("RGB").save(buf, format="JPEG", quality=95)
        mime = "image/jpeg"
    return UprightImage(buf.getvalue(), mime, upright.width, upright.height)
