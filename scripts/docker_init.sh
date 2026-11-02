#!/bin/sh
# 容器啟動時的初始化：建表 → 匯入參考資料 → 匯入 RAG 語料。三步都可重複執行（冪等）。
set -eu

echo "[init] alembic upgrade head"
alembic upgrade head

echo "[init] 匯入參考資料 (app.db.import_catalog)"
python -m app.db.import_catalog

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    echo "[init] 警告：沒有設 OPENROUTER_API_KEY，跳過 RAG 語料匯入（檢索會沒有資料）" >&2
elif ! python -m app.rag.ingest; then
    echo "[init] 警告：RAG 語料匯入失敗，先照常啟動；修正後重啟 backend 即可補匯入" >&2
fi

echo "[init] 完成"
