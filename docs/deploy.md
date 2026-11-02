# 本機一鍵部署（Docker）

一個指令把資料庫、後端、前端一起跑起來，並自動建表、匯入參考資料。只做本機，不是雲端部署。

```
瀏覽器 ──> frontend (nginx, 127.0.0.1:8080)
              ├─ 靜態頁面（SPA，找不到的路徑回 index.html）
              └─ /api/*  ──> backend (uvicorn:8000, 只在容器網路內)
                                └──> db (PostgreSQL + pgvector, 127.0.0.1:5433)
```

## 一個指令

需要 Docker Desktop。不必先裝 Python、uv、Node。

```bash
cp .env.example .env     # 只需填 POSTGRES_PASSWORD（英數字，不要含 @ : / #）
docker compose up -d --build
```

等約 1 分鐘（第一次要建映像），然後：

- 前端首頁：http://127.0.0.1:8080
- 健康檢查：http://127.0.0.1:8080/api/health 回 `{"status":"ok"}`

## 要填哪些變數（`.env`）

| 變數 | 說明 |
|---|---|
| `POSTGRES_PASSWORD` | **必填**。資料庫密碼；`DATABASE_URL` 容器內會自動組，不用管 |
| `OPENROUTER_API_KEY` | 選填。沒填時 RAG 語料匯入會跳過並印警告，系統其他部分照常運作 |
| `EMBEDDING_MODEL` | 有 `OPENROUTER_API_KEY` 時 RAG 匯入要用，範本已填 |
| `EXTRACTOR` | `stub`（假資料，預設）或 `openrouter`（真辨識，需金鑰與型號） |
| `NARRATOR` | `template`（預設）或 `openrouter` |
| `AUTH` | `test`（預設，固定測試帳號）或 `google`（需 `GOOGLE_CLIENT_ID`、`SESSION_SECRET`） |
| `DB_PORT`、`FRONTEND_PORT` | 對外連接埠，預設 5433、8080，只綁 127.0.0.1；埠被占用時改這裡 |

容器內的後端固定使用 `CATALOG_SOURCE=pg`、`STORE=pg`，不看 `.env` 裡這兩項。
金鑰只在執行時由 `.env` 注入，不會寫進映像，`.env` 也不進 git。

## 啟動時做了什麼

backend 容器啟動會執行 `scripts/docker_init.sh`，依序：

1. `alembic upgrade head`：建表
2. `python -m app.db.import_catalog`：匯入參考資料
3. `python -m app.rag.ingest`：匯入 RAG 語料。沒有 `OPENROUTER_API_KEY` 時跳過；匯入失敗也只警告、後端照常啟動。結尾會印一行 `RAG 狀態`（已匯入幾段／跳過原因）

三步都可重複執行，重跑不會重複匯入。

## 啟動後檢查 RAG 語料

報告沒有腳註時，先確認語料有沒有匯入：

```bash
docker compose logs backend | grep "RAG 狀態"
docker compose exec db psql -U g4 -c "select count(*) from evidence.chunks"
```

段數要大於 0。為 0 通常是沒設 `OPENROUTER_API_KEY`（或匯入失敗）；補好 `.env` 後 `docker compose up -d --force-recreate backend` 重跑初始化。

## 看 log

```bash
docker compose logs -f backend     # 初始化訊息（[init] 開頭）與 API log
docker compose logs -f frontend
docker compose ps                  # 狀態；backend 顯示 healthy 才算好
```

## 重新啟動、重置

```bash
docker compose restart backend     # 重跑初始化（補匯入 RAG 語料時用）
docker compose down                # 停止，資料保留
docker compose down -v             # 停止並刪除資料庫資料，之後重來
docker compose up -d --build       # 改了程式碼後重建
```

## 同時跑多套（例如測試）

用不同 project name 和連接埠，避免互相衝突：

```bash
DB_PORT=5543 FRONTEND_PORT=8580 docker compose -p g4-test up -d --build
docker compose -p g4-test down -v
```

## 常見問題

- `請先複製 .env.example 成 .env`：沒建 `.env` 或沒填 `POSTGRES_PASSWORD`。
- 埠被占用：改 `.env` 的 `DB_PORT`（預設 5433）、`FRONTEND_PORT`（預設 8080）這兩個變數；不設則維持預設。
- 密碼含特殊符號導致 backend 連不上資料庫：換成純英數字，再 `docker compose down -v` 重來（舊資料庫還是舊密碼）。
