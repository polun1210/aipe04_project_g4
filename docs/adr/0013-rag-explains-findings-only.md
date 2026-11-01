# RAG 只解釋判定，不參與判定；語料在建置時固定

> 設計決策的參考紀錄，不是硬性規定；想調整請見 [README](README.md)。

所有判定（哪些藥與成分有交互作用、攝取量有沒有超過上限）都只來自規則表與 DRIs 上限計算，由確定性程式產生。
RAG（檢索增強生成，retrieval-augmented generation）只用在報告層：它在系統內事先 ingest 好的語料裡，替**已經存在的判定**找原文佐證，
交給 LLM 寫成白話，並且每則說明附上引用。RAG 不能新增、刪除或改變任何判定。

這份決定修改了 [ADR-0006](0006-evidence-sources-build-time-only.md)：
「出處只在建表時決定」放寬成「**判定的出處在建表時決定；解釋可以引用內部語料**」。
ADR-0006 拒絕「每次評估即時查外部資料庫」的理由（結果不可重現、證據整合無法程式化、外部依賴）仍然成立，所以：

- 語料在建置時固定，放在 git 的 `data/sources/`，由 `python -m app.rag.ingest` 切塊寫進 `evidence.chunks`；
- 執行期只在系統自己的資料庫裡檢索，**不呼叫任何外部資料庫**（執行期唯一的外部呼叫是把查詢文字轉成向量的 embedding 服務）；
- 後台知識庫（醫療知識庫）的 API 第一版不串接，判斷仍用 CSV＋資料庫。

## 語料

| 來源 | 內容 | 位置 |
|---|---|---|
| NIH ODS HealthProfessional | 13 種營養素 fact sheet 原文 | `data/sources/nih_ods/` |
| NCCIH | 紅麴、魚油、葡萄糖胺頁面原文 | `data/sources/nccih/` |
| DRIs 摘要 | 總表與整理筆記（不含 2.3 MB 的全文 `DRIs_Full.md`，它不進語料） | `data/sources/dris/` |
| TFDA 代表仿單 | `drug_items` 每個有效成分只取日期最新的一份，去掉 base64 圖片 | `data/sources/tfda/<有效成分>/<許可證字號>.md` |

仿單由 `scripts/build_tfda_corpus.py` 從 nutrition-agent 的 `knowledge/raw/tfda/` 挑出，檔頭註明許可證字號、原始檔名與抓取日期；
排除轉檔後只有「目前無仿單資料」的空檔。要更新就重跑腳本、重新 ingest。

每份文件在 `catalog.source_documents` 有一列：`import_catalog` 除了引文引用的文件，也會把 `data/sources/` 裡沒被引用的文件登記進去。
規則的引文（`catalog.citations`）和 RAG 切塊（`evidence.chunks`）因此指向同一張表：判定的依據和解釋的依據是同一批文件，
都能回溯到原檔第幾行。

## 檢索

`retrieve_evidence(conn, embedder, 成分, 藥的有效成分, limit=8)`：

1. 用切塊的成分標記（`ingredient_codes && 代碼陣列`）篩選：NIH ODS／NCCIH 依檔名，仿單依資料夾名稱，DRIs 依段落提到的成分名稱；
2. 依查詢文字（成分、藥、藥物類別的中英文名稱）與切塊的餘弦相似度排序；
3. 每份文件最多先取 2 段（仿單每段都提到藥名，不限制會佔滿結果），名額有剩再依相似度補滿。

不建向量索引：4096 維超過 pgvector 近似索引的上限，而先用成分標籤篩選後只剩幾十到幾百塊，循序掃描就夠快。

切塊 ID 由「文件路徑＋章節＋內容」雜湊而來，重跑 ingest 只替新增的塊算 embedding。

## 型號必填

embedding 型號由環境變數 `EMBEDDING_MODEL` 指定，**沒有預設值，沒設就報錯**（理由同 [ADR-0011](0011-narration-model-claude-haiku-5-5.md) 的 `NARRATOR_MODEL`：
型號被悄悄換掉，新舊向量就不能混用，結果也無法追溯）。型號跟著每個切塊存進 `embedding_model`，檢索只比同型號的塊；換型號後重跑 ingest 會整批重算。

## Consequences

- 規則本身不因 RAG 而改變：同一個人評估兩次，判定一定相同；只有白話解釋的措辭與引用段落可能不同。
- RAG 的品質用 `evals/rag/run.py` 量：每題預期的原文段落有沒有出現在前 8 名。題組是離線寫死的，不看哪種檢索做法找得到。
- 語料有缺口：某個組合在補充劑端若沒有原文，解釋只能引用仿單端或 DRIs，不能憑空補。例如沒有維生素 K 的 NIH 專業版（維生素 K 也不是目標營養素，
  只在 DRIs 總表與其他文件順帶提到）；PPI × 鈣的規則已退役，Calcium 原文只把 PPI 列為「可能相關」。缺口清單見 PR 說明。
- 語料中的仿單是「每個有效成分一份代表」，不是全部學名藥；仿單內容以原廠或代表性許可證為準，不代表所有同成分藥品。
- 檢索需要資料庫與 embedding 服務；兩者任一不可用時，報告退回只用規則引文加固定模板（C-3 實作）。
