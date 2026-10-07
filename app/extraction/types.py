"""辨識模組對外的輸入與錯誤型別。"""

from app.schemas.common import StrictModel


class ImageInput(StrictModel):
    image_id: str  # 檔名即編號，例如 p03-img01
    content: bytes  # 原始上傳檔


class ExtractionError(Exception):
    """引擎逾時、找不到錄製回應、回傳格式錯誤等。由後端轉成 JobResponse(status=failed)。"""
