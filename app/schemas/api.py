"""API 共用外框。

成功：直接回資料本體（各交接點的模型），不另外包一層。
失敗：一律回 ErrorResponse。
所有網址同步回傳：辨識（保健食品、藥包）、評估、LLM 報告都是前端顯示「處理中…」等回應，不建工作編號。
辨識服務逾時或失敗 → ErrorResponse(code = extraction_failed)。
全部照片都沒通過品質檢查 → 不回草稿，改回 ErrorResponse(code = all_images_rejected)，
details 每張照片一行，例如 "img-02：反光"。

端點一覽（對照 docs/schemas/README.md）：
  GET  /api/catalog                               → CatalogResponse
  POST /api/drug-drafts          (multipart: images) → DrugDraft（201）
  GET  /api/drugs/lookup?name=…                   → DrugLookupResponse
  POST /api/supplement-drafts    (multipart: ingredient_images, nutrition_images, category) → ExtractionDraft（201）
  POST /api/products                              ← VerificationSubmission → ProductCreated（201）
  POST /api/assessments                           ← AssessmentRequest → Assessment（確定性計算，同步回傳）
  POST /api/assessments/{case_id}/report          → Report（201；已產生過回 200 與同一份）
  GET  /api/reports?date_from=…&date_to=…         → list[ReportSummary]
  GET  /api/reports/{report_id}                   → Report
  GET  /api/health                                → {"status": "ok"}
"""

from uuid import UUID

from app.schemas.common import StrictModel
from app.schemas.enums import ErrorCode


class ErrorBody(StrictModel):
    code: ErrorCode
    message: str  # 給使用者看的中文訊息，不可洩漏內部細節
    details: list[str] | None = None  # 例如欄位驗證錯誤


class ErrorResponse(StrictModel):
    error: ErrorBody


class ProductCreated(StrictModel):
    product_id: UUID
