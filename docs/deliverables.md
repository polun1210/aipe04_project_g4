# 交付物清單

老師 W4 要求交付「規則來源、覆核紀錄、案例」。下表是 repo 內可自動產生或直接取得的部分。

| 交付物 | 內容 | 怎麼取得 | 對應驗收項 |
|---|---|---|---|
| `rules.csv` | 規則清單，含狀態（`status`）、整理者（`curated_by`）、覆核者與日期（`reviewed_by`、`reviewed_at`） | 匯出腳本 | 規則來源、覆核紀錄 |
| `citations.csv` | 規則引用的來源：網址、段落、原文引文、擷取日期、來源版本 | 匯出腳本 | 規則來源 |
| `VERSION` | 資料版本，報告與評估個案都會記錄它 | 匯出腳本 | 可追溯性 |
| 回歸測試紀錄 | `uv run pytest -q` 的結果摘要（見下） | 自行執行 | 測試與品質 |
| 案例 | 範例個案、評估與報告 JSON：`docs/schemas/examples/`；串接流程見 `scripts/e2e_smoke.py` | 直接取得 | 案例 |

## 怎麼產生

```bash
uv run python scripts/export_deliverables.py          # 輸出到 build/deliverables/（不進 git）
uv run python scripts/export_deliverables.py --out 其他資料夾
```

腳本同時做兩項檢查並印出結果（有問題時結束碼為 1）：

- `citations.csv` 的 `url` 欄是否有空白列
- 規則的 `citation_ids`（以 `|` 分隔）是否都能在 `citations.csv` 找到

腳本只列出問題，不會自動補。

## 目前檢查結果（資料版本 2026.11.1）

- 規則 17 條：`reviewed` 11、`retired` 5、`draft` 1
- 引用 20 筆，`url` 欄空白：無
- 規則引用不存在的 `citation_id`：無
- 覆核欄（`reviewed_by`／`reviewed_at`）有空白：`glucosamine-rx-duplicate`（狀態 `draft`，待組長審）

## 回歸測試紀錄

執行 `uv run pytest -q` 的結果摘要（2026-11-02，基於 main `e97cbe5` 加上本 PR 的測試）：

| 條件 | 結果 |
|---|---|
| 沒設 `DATABASE_URL` | 662 passed、69 skipped（資料庫測試略過） |
| 設 `DATABASE_URL`（本機 PostgreSQL，已 migrate 並匯入目錄） | 731 passed |

之後如要更新，重跑指令並覆寫上表，不要沿用舊數字。
