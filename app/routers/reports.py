from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator

from app.errors import ApiError
from app.report_chat import ReportChat, ReportChatError, get_report_chat
from app.reporting import Reporter, get_reporter
from app.schemas.api import ErrorResponse
from app.schemas.enums import ErrorCode
from app.schemas.report import Report, ReportSummary
from app.auth import get_current_user_id
from app.store import Store, get_store

router = APIRouter(tags=["報告"])

_NOT_FOUND = {404: {"model": ErrorResponse, "description": "找不到這筆資料，或不是自己的"}}


@router.post(
    "/api/assessments/{case_id}/report",
    response_model=Report,
    status_code=201,
    summary="產生報告",
    description=(
        "PG-008 報告呈現頁載入時呼叫。這個個案第一次產生回 201；已經產生過就回 200 與同一份報告，"
        "不重新產生，保證同一份評估的報告一致。"
    ),
    responses={
        200: {"model": Report, "description": "這個個案已經有報告，回同一份"},
        **_NOT_FOUND,
    },
)
def create_report(
    case_id: UUID,
    response: Response,
    reporter: Reporter = Depends(get_reporter),
    store: Store = Depends(get_store),
    user_id: UUID = Depends(get_current_user_id),
) -> Report:
    existing = store.get_report_by_case(user_id, case_id)
    if existing is not None:
        response.status_code = 200
        return existing
    found = store.get_case(user_id, case_id)
    if found is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "找不到要求的資料")
    case, assessment = found
    report = reporter.build(case, assessment, datetime.now(UTC))
    # 同時送兩次時，後到的那份不會存進去；回實際存著的那份，前端拿到的 report_id 才查得到
    stored = store.save_report(user_id, report)
    if stored.report_id != report.report_id:
        response.status_code = 200  # 跟「已經產生過」一樣
    return stored


@router.get(
    "/api/reports",
    response_model=list[ReportSummary],
    summary="依日期範圍列出報告記錄",
    description=(
        "PG-011 報告記錄查詢頁呼叫。兩個日期都選填、含當天，以台灣時間判斷；依產生時間新到舊。"
        "「今天／最近 7 天／最近 30 天／本月」由前端換算成日期。"
    ),
    responses={422: {"model": ErrorResponse, "description": "開始日期晚於結束日期"}},
)
def list_reports(
    date_from: date | None = Query(default=None, description="開始日期 YYYY-MM-DD（含）"),
    date_to: date | None = Query(default=None, description="結束日期 YYYY-MM-DD（含）"),
    store: Store = Depends(get_store),
    user_id: UUID = Depends(get_current_user_id),
) -> list[ReportSummary]:
    if date_from and date_to and date_from > date_to:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, "送出的資料有欄位需要修正", ["date_from：開始日期不可晚於結束日期"]
        )
    return [
        ReportSummary(
            report_id=r.report_id,
            case_id=r.case_id,
            generated_at=r.generated_at,
            drug_count=len(r.profile.drugs),
            product_count=len(r.products),
        )
        for r in store.list_reports(user_id, date_from, date_to)
    ]


@router.get(
    "/api/reports/{report_id}",
    response_model=Report,
    summary="取得單份報告",
    description="PG-012 報告記錄詳細資料頁呼叫，回傳凍結的完整報告。",
    responses=_NOT_FOUND,
)
def get_report(
    report_id: UUID,
    store: Store = Depends(get_store),
    user_id: UUID = Depends(get_current_user_id),
) -> Report:
    report = store.get_report(user_id, report_id)
    if report is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "找不到要求的資料")
    return report


class ChatRequest(BaseModel):
    question: str = Field(max_length=500)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("問題不可為空白")
        return value


class ChatResponse(BaseModel):
    answer: str


@router.post(
    "/api/reports/{report_id}/chat",
    response_model=ChatResponse,
    summary="問這份報告",
    description=(
        "報告頁對話面板呼叫。只依這一份報告回答，不存對話。"
        "NARRATOR 不是 openrouter 時回 503（chat_disabled）；LLM 失敗回 502（chat_failed）。"
    ),
    responses={
        **_NOT_FOUND,
        503: {"model": ErrorResponse, "description": "對話功能未啟用"},
        502: {"model": ErrorResponse, "description": "LLM 逾時或失敗"},
    },
)
def chat_about_report(
    report_id: UUID,
    body: ChatRequest,
    chat: ReportChat | None = Depends(get_report_chat),
    store: Store = Depends(get_store),
    user_id: UUID = Depends(get_current_user_id),
) -> ChatResponse:
    report = store.get_report(user_id, report_id)
    if report is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "找不到要求的資料")
    if chat is None:
        raise ApiError(503, ErrorCode.CHAT_DISABLED, "對話功能未啟用")
    try:
        answer = chat.answer(report.model_dump_json(), body.question)
    except ReportChatError as e:
        raise ApiError(502, ErrorCode.CHAT_FAILED, "暫時無法回答，請稍後再試") from e
    # 回答檢查（ticket 04）接在這裡：檢查 answer，不合格就改回固定訊息
    return ChatResponse(answer=answer)
