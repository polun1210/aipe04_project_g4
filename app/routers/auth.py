from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.auth import GoogleIdentity, auth_mode, get_current_user_id, get_google_verifier
from app.errors import ApiError
from app.schemas.api import ErrorResponse, GoogleLoginRequest, MeResponse
from app.schemas.enums import ErrorCode
from app.store import Store, get_store

router = APIRouter(tags=["帳號"])

_UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "沒登入，或 Google 憑證無效"}}


def _me(store: Store, user_id: UUID) -> MeResponse:
    user = store.get_user(user_id)
    if user is None:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "請先登入")
    return MeResponse(user_id=user.user_id, email=user.email, name=user.name)


@router.post(
    "/api/auth/google",
    response_model=MeResponse,
    summary="Google 登入",
    description="PG-002 登入頁送出 Google ID token；成功後設定 session cookie。AUTH=test 時回 404。",
    responses={**_UNAUTHORIZED, 404: {"model": ErrorResponse, "description": "目前是測試模式（AUTH=test）"}},
)
def google_login(
    body: GoogleLoginRequest,
    request: Request,
    store: Store = Depends(get_store),
    verify: Callable[[str], GoogleIdentity] = Depends(get_google_verifier),
) -> MeResponse:
    if auth_mode() == "test":
        raise ApiError(404, ErrorCode.NOT_FOUND, "找不到要求的資料")
    identity = verify(body.credential)
    user_id = store.find_or_create_google_user(identity.sub, identity.email, identity.name)
    request.session.clear()
    request.session["user_id"] = str(user_id)
    return _me(store, user_id)


@router.get("/api/me", response_model=MeResponse, summary="目前登入者", responses=_UNAUTHORIZED)
def get_me(store: Store = Depends(get_store), user_id: UUID = Depends(get_current_user_id)) -> MeResponse:
    return _me(store, user_id)


@router.post("/api/logout", status_code=204, summary="登出（沒登入也回 204）")
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)
