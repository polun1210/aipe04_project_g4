"""資料庫連線池。第一次用到時建立並開啟；伺服器關閉時由 lifespan 關掉（見 app/main.py）。"""

from psycopg_pool import ConnectionPool

from app.db.config import database_url

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        pool = ConnectionPool(database_url(), min_size=1, max_size=10, open=False)
        pool.open(wait=True, timeout=10)  # 連不上資料庫就在啟動時失敗，而不是等第一個請求
        _pool = pool
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
