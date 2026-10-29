# 正式藥品名稱搜尋交接

本次 PR 疊在尚未合併的 PR #60 上；base 為 `frontend/member-health-profile`。

## 已有後端能力

`GET /api/catalog` 提供 16 類用藥的代碼、中文名稱與說明，前端實際呼叫此 API 載入類別。來源與型別沿用 `app/schemas/catalog.py` 的 DrugClass。

`GET /api/drugs/lookup?name=...` 目前只查 `docs/schemas/examples/catalog/drug_items.csv` 的成分與商品名範例，最多回傳 10 筆，沒有類別搜尋參數、正式品項 ID、規格或許可證字號。因此本 PR 不把它當成正式藥品搜尋服務，也不先查 10 筆再前端過濾而漏掉其他類別候選。

## 已完成前端

- 先選類別再輸入藥品名稱；停止輸入 300ms 後查詢，亦可按查詢按鈕重試。
- 各列各自維護查詢、載入、錯誤、無結果與候選選取狀態；舊查詢、切換類別、修改輸入、取消或離頁後的回應不能覆蓋目前資料。
- 候選顯示名稱、規格、許可證字號；未提供的資訊明確顯示「未提供」。使用穩定品項 ID 區分同名藥品。
- 必須實際從候選中選取才可儲存，之後才能鎖定、下一步。單純 OCR 文字、自由輸入與一鍵鎖定都不能繞過。
- 原始辨識草稿、來源圖片、批次及既有評估 payload 保留；送出仍沿用 name 與 draft_id／row_id，不擅自修改後端契約。選到的品項資訊只存本機校對狀態。

## 未開放的功能與整合位置

正式藥品搜尋 API 尚未提供，預設 `MedicineSearchGateway.available=false`，顯示未開放說明、停用查詢／儲存／鎖定；無法完成含藥品的校對下一步。仍可上傳並保留辨識草稿與圖片。未提供用藥資料的既有保健食品流程不變。前端沒有正式藥品假清單，測試候選僅在測試中注入。

`frontend/src/services/medicineSearchGateway.ts` 是前端 adapter 介面，**不是新訂的 HTTP 契約**。正式後端確定後，以 `app.provide(medicineSearchGatewayKey, implementation)` 提供真正的搜尋實作，再開啟 available：

- 輸入既有 drug_class_code 與使用者查詢文字，搜尋應先限制該類別，再進行模糊搜尋及分頁／限制結果。
- 將真實回應映射到前端 `MedicineCandidate`：穩定品項 id、name、drugClassCode、specification、licenseNumber。後兩者缺資料時用 null，不能捏造。
- Promise 失敗必須 reject；不能把 API 失敗當空結果。
- 候選類別必須與查詢類別一致；重複 ID、無法辨識的資料不使用。

需後端／組長確認正式資料來源、搜尋 API 路徑與欄位、穩定品項 ID、類別關聯及模糊搜尋規則。若未來評估需傳品項 ID，請另行確認契約；本 PR 沒有添加該欄位，也沒有重做登入或變動其他 PR。
