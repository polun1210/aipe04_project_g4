"""「目前是誰」：每個網址都透過 Depends(get_current_user_id) 取得使用者編號。

用環境變數 AUTH 切換：
- test（沒設時的預設，開發與 CI 用）：一律回固定的測試帳號
- google：從 session cookie 讀登入者；沒登入回 401。登入走 POST /api/auth/google（Google ID token）
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.errors import ApiError
from app.schemas.enums import ErrorCode
from app.store import TEST_USER_ID, Store, get_store

_LOGIN_FAILED = "Google 登入失敗，請再試一次"
_NEED_LOGIN = "請先登入"


def auth_mode() -> str:
    mode = os.environ.get("AUTH", "test")
    if mode not in ("test", "google"):
        raise ValueError(f"AUTH 只能是 test 或 google，收到 {mode!r}")
    return mode


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str | None
    name: str | None


def get_google_verifier() -> Callable[[str], GoogleIdentity]:
    """回傳驗證函式；做成 dependency，測試可用 dependency_overrides 換掉，不連 Google。"""

    def verify(credential: str) -> GoogleIdentity:
        try:
            info = id_token.verify_oauth2_token(
                credential, google_requests.Request(), os.environ.get("GOOGLE_CLIENT_ID")
            )
        except ValueError as e:
            raise ApiError(401, ErrorCode.UNAUTHORIZED, _LOGIN_FAILED) from e
        return GoogleIdentity(sub=info["sub"], email=info.get("email"), name=info.get("name"))

    return verify


def get_current_user_id(request: Request, store: Store = Depends(get_store)) -> UUID:
    if auth_mode() == "test":
        return TEST_USER_ID
    try:
        user_id = UUID(request.session["user_id"])
    except (KeyError, ValueError, TypeError) as e:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, _NEED_LOGIN) from e
    if store.get_user(user_id) is None:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, _NEED_LOGIN)
    return user_id
