# 健康資料與 Google 登入整合交接

目前 main 的後端僅提供目錄、辨識、產品、評估與報告 API；沒有會員資料讀寫或首次健康資料完成狀態 API。`app/auth.py` 仍回傳固定測試帳號。這次沒有新增或猜測 HTTP 路徑、變更後端資料契約，也沒有實作 Google OAuth。

## 已交付的前端入口

- `/health-profile`：首次健康資料填寫，先填慢性疾病；只有實際儲存成功後才導向 `/medicine-upload`。
- `/settings`：出生年、出生月、性別與慢性疾病。載入成功後才允許儲存；失敗保留編輯內容，取消返回會員中心。
- `ConditionSelector.vue`：註冊、首次填寫與會員設定共用；沿用原來五個代碼及「以上皆無」互斥邏輯。

目前應用未提供會員服務實作，兩頁皆明確標示儲存未開放、停用儲存按鈕。沒有假登入、假儲存成功或 localStorage 持久化。原有測試帳號辨識流程不變。

## 待組員 C 與後端確認後串接

`frontend/src/services/healthProfileGateway.ts` 是前端依賴注入介面，**不是新的後端 API 契約**。實際 HTTP 契約確認後，在應用啟動處用 `app.provide(healthProfileGatewayKey, implementation)` 提供實作：

- `available`：只有會員讀寫已可實際使用時設為 true。
- `loadProfile()`：取得目前使用者的真實帳號資料；不得回傳固定測試帳號冒充登入者。
- `saveProfile(profile)`：依現有 `AccountProfile` 形狀傳遞 `birth_year`、`birth_month`、`sex`、`conditions`；成功前不得 resolve，失敗須 reject。
- `saveInitialConditions(conditions)`：將首次填寫資料交給已確認的 API；不得只寫前端記憶體便回報成功。首次流程如何取得出生年、月、性別，需與實際註冊／會員契約一起確認。

慢性病沿用 `{ selected: ConditionCode[], none_selected: boolean }`；`selected=[]` 且 `none_selected=true` 是有效答案。性別僅用 `male`／`female`。設定頁出生年驗證沿用後端 1900–2100 範圍，出生月為 1–12。

首次填寫完成狀態必須由後端提供，不可只用 selected 是否為空判斷；本 PR 沒有發明完成狀態欄位。Google 登入成功後由組員 C 的登入流程讀取該狀態：

1. 從「開始使用」進入：未完成 → `/health-profile`，已完成 → `/medicine-upload`。
2. 從導覽列登入：可返回 `/`。
3. 只有健康資料 API 成功後才能繼續辨識；已完成者不重填。

目前未改寫首頁、LoginView 或 OAuth callback，避免與組員 C 重複實作。請待契約確認後再串接登入來源意圖與完成狀態檢查。

## 密碼介面

既有登入與註冊頁仍有 email／密碼，尚無證據表示只保留 Google 登入，因此設定頁保留密碼輸入介面並標示未開放。密碼不包含在健康資料服務參數中；本 PR 未修改任何認證或密碼變更機制。
