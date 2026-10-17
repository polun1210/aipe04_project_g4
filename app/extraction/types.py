"""辨識模組對外的輸入與錯誤型別。"""

from app.schemas.common import StrictModel
from app.schemas.enums import ImageKind


class ImageInput(StrictModel):
    image_id: str  # 檔名即編號，例如 p03-img01
    content: bytes  # 原始上傳檔
    image_kind: ImageKind | None = None  # 上傳網址一定會填；內部測試可以不填


class ExtractionError(Exception):
    """引擎逾時、找不到錄製回應、回傳格式錯誤等。由後端轉成 ErrorResponse(code=extraction_failed)。"""
