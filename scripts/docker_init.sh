#!/bin/sh
# 容器啟動時的初始化：建表 → 匯入參考資料 → 匯入 RAG 語料。三步都可重複執行（冪等）。
# RAG 匯入失敗只警告、不擋啟動；結尾會印一行 RAG 狀態。
set -eu

echo "[init] alembic upgrade head"
alembic upgrade head

echo "[init] 匯入參考資料 (app.db.import_catalog)"
python -m app.db.import_catalog

RAG_STATUS=""
if [ -z "${OPENROUTER_API_KEY:-}" ]; then
    RAG_STATUS="已跳過（沒有設 OPENROUTER_API_KEY）"
elif ! python -m app.rag.ingest; then
    RAG_STATUS="匯入失敗（見上方錯誤；修正後 docker compose restart backend）"
fi

CHUNKS=$(python -c "
import psycopg, os
with psycopg.connect(os.environ['DATABASE_URL']) as c:
    print(c.execute('SELECT count(*) FROM evidence.chunks').fetchone()[0])
" 2>/dev/null || echo "?")

if [ -z "$RAG_STATUS" ]; then
    echo "[init] RAG 狀態：已匯入，目前語料 ${CHUNKS} 段"
else
    echo "[init] ==== 警告 ==== RAG 狀態：${RAG_STATUS}；目前語料 ${CHUNKS} 段（報告沒有腳註時先看這個）" >&2
fi

echo "[init] 完成"
