"""上傳照片的共用處理：上傳檔 → ImageInput、品質檢查結果 → 錯誤回應、辨識失敗 → 502。"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import UploadFile

from app.errors import ApiError
from app.extraction import ExtractionError, ImageInput
from app.schemas.enums import ErrorCode, ImageKind, QualityStatus, RejectReason
from app.schemas.label import SourceImage

REJECT_REASON_ZH: dict[RejectReason, str] = {
    RejectReason.BLUR: "模糊",
    RejectReason.GLARE: "反光",
    RejectReason.TRUNCATED: "被裁切",
    RejectReason.SKEW: "歪斜",
    RejectReason.LOW_RESOLUTION: "解析度不足",
    RejectReason.UNSUPPORTED_LABEL: "不是中文營養標示",
    RejectReason.LOW_LIGHT: "光線不足",
}

_VALIDATION_MESSAGE = "送出的資料有欄位需要修正"
_ALL_REJECTED_MESSAGE = "照片都不夠清楚，請重新拍攝"
_EXTRACTION_FAILED_MESSAGE = "照片辨識失敗，請稍後再試"


def to_image_inputs(groups: list[tuple[ImageKind, list[UploadFile]]]) -> list[ImageInput]:
    """依序把各欄位的上傳檔轉成 ImageInput，image_id 跨欄位連續編號（img-01、img-02…）。

    只做最低限度的檢查：合計至少 1 張，且 content_type 以 image/ 開頭。
    檔案大小、張數上限、真正的格式檢查由別的組員寫成共用函式，之後替換這裡。
    """
    files = [(kind, f) for kind, group in groups for f in group]
    if not files:
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, ["請至少上傳 1 張照片"])
    inputs = []
    for number, (kind, upload) in enumerate(files, start=1):
        image_id = f"img-{number:02d}"
        if not (upload.content_type or "").startswith("image/"):
            raise ApiError(422, ErrorCode.VALIDATION_ERROR, _VALIDATION_MESSAGE, [f"{image_id}：只接受圖片檔"])
        inputs.append(ImageInput(image_id=image_id, content=upload.file.read(), image_kind=kind))
    return inputs


def ensure_any_accepted(quality: list[SourceImage]) -> None:
    """全部照片都沒通過品質檢查就不回草稿，改回 422，details 每張一行。"""
    if any(s.quality_status is QualityStatus.ACCEPTED for s in quality):
        return
    details = [f"{s.image_id}：{REJECT_REASON_ZH[s.reject_reason]}" for s in quality if s.reject_reason]
    raise ApiError(422, ErrorCode.ALL_IMAGES_REJECTED, _ALL_REJECTED_MESSAGE, details)


@contextmanager
def extraction_errors_as_api_error() -> Iterator[None]:
    """辨識模組的 ExtractionError 一律轉成 502 extraction_failed。"""
    try:
        yield
    except ExtractionError as e:
        raise ApiError(502, ErrorCode.EXTRACTION_FAILED, _EXTRACTION_FAILED_MESSAGE) from e
