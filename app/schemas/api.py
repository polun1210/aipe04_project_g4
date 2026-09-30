"""API 共用外框。

成功：直接回資料本體（各交接點的模型），不另外包一層。
失敗：一律回 ErrorResponse。
長時間工作（辨識、報告生成）：POST 回 202 ＋ JobAccepted，前端每 2 秒 GET 一次 JobResponse。

端點一覽：
  GET  /api/catalog                               → CatalogResponse
  POST /api/extractions            (multipart)    → ExtractionAccepted
  GET  /api/extractions/{job_id}                  → JobResponse[ExtractionDraft]
  PUT  /api/products/{product_id}/verification    ← VerificationSubmission → 204
  POST /api/assessments                           ← AssessmentRequest → JobAccepted
  GET  /api/assessments/jobs/{job_id}             → JobResponse[Report]
"""

from typing import Generic, TypeVar

from pydantic import model_validator

from app.schemas.common import StrictModel
from app.schemas.enums import ErrorCode, JobStatus

T = TypeVar("T")


class ErrorBody(StrictModel):
    code: ErrorCode
    message: str  # 給使用者看的中文訊息，不可洩漏內部細節
    details: list[str] | None = None  # 例如欄位驗證錯誤


class ErrorResponse(StrictModel):
    error: ErrorBody


class JobAccepted(StrictModel):
    job_id: str


class JobResponse(StrictModel, Generic[T]):
    job_id: str
    status: JobStatus
    result: T | None = None  # 只在 done 時有值
    error: ErrorBody | None = None  # 只在 failed 時有值

    @model_validator(mode="after")
    def _payload_matches_status(self) -> "JobResponse[T]":
        if (self.status is JobStatus.DONE) != (self.result is not None):
            raise ValueError("result 只在 status = done 時有值，且必有")
        if (self.status is JobStatus.FAILED) != (self.error is not None):
            raise ValueError("error 只在 status = failed 時有值，且必有")
        return self
