"""「目前是誰」：每個網址都透過 Depends(get_current_user_id) 取得使用者編號。

現在還沒有登入，一律回固定的測試帳號。昊昀的登入（工作階段或 token）好了之後，
只要把這個函式換成真的檢查：沒登入回 401，網址本身不用改。
"""

from uuid import UUID

from app.store import TEST_USER_ID


def get_current_user_id() -> UUID:
    return TEST_USER_ID
