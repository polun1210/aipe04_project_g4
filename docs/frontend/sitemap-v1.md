# 網站站點地圖 (Sitemap)

本文件定義網站之頁面結構、階層關係與主要功能對應。

## 1. 網站頁面樹狀結構 (Site Tree)

```
網站
└── 首頁 (Home)
    ├── 會員認證 (Authentication)
    │   ├── 註冊 (Register)
    │   └── 登入 (Login)
    │
    ├── 分析與報告流程 (Analysis & Report Flow)
    │   └── 使用者輸入 1 (User Input Step 1)
    │       └── 圖片上傳 (Image Upload)
    │           └── 辨識結果 (Recognition Result)
    │               └── 使用者輸入 2 (User Input Step 2)
    │                   └── 過渡頁面 (Transition / Loading Page)
    │                       └── 報告呈現 (Report Display)
    │
    └── 會員中心 (Member Center)
        ├── 設定 (Settings)
        └── 報告記錄查詢 (Report History)
            └── 報告記錄詳細資料 (Report History Detail)

```

## 2. 頁面詳細說明與路由對應 (Pages & Routes)

### 2.1 主要頁面 (Main Pages)

* **首頁 (`/`)**：網站入口，提供核心服務介紹與主要功能導引。

### 2.2 會員認證 (Authentication)

* **註冊頁面 (`/auth/register`)**：提供新使用者建立帳號。

* **登入頁面 (`/auth/login`)**：提供既有使用者登入系統。

### 2.3 分析與報告流程 (Analysis & Report Flow)

* **使用者輸入 第一階段 (`/flow/input-1`)**：初步資料填寫或選擇。

* **圖片上傳 (`/flow/upload`)**：支援使用者上傳待辨識之圖片。

* **辨識結果 (`/flow/recognition-result`)**：展示圖片 AI/系統辨識結果供使用者確認。

* **使用者輸入 第二階段 (`/flow/input-2`)**：補充額外資訊或調整辨識參數。

* **過渡頁面 (`/flow/processing`)**：資料處理與報告生成中的等待/加載頁面。

* **報告呈現 (`/flow/report`)**：最終分析報告之展示與下載/分享功能。

### 2.4 會員中心 (Member Center)

* **會員中心主頁 (`/user`)**：會員功能總覽與個人資訊摘要。

* **帳號設定 (`/user/settings`)**：個人資料修改、密碼變更與通知設定。

* **報告記錄查詢 (`/user/reports`)**：歷史產生之報告列表與搜尋/篩選。

* **報告記錄詳細資料 (`/user/reports/:id`)**：特定歷史報告之詳細內容檢視。

## 3. 權限與存取控制 (Access Control)

| 頁面分類 | 頁面名稱 | 存取權限 | 備註 | 
| ----- | ----- | ----- | ----- | 
| **首頁** | 首頁 | 公開 (Public) |  | 
| **認證** | 註冊 / 登入 | 訪客 (Guest) | 已登入者自動轉址至首頁 | 
| **分析流程** | 輸入、上傳、辨識、報告 | 會員(Authenticated) | 需登入才能使用完整流程 | 
| **會員中心** | 設定、報告記錄與詳情 | 會員 (Authenticated) | 需完成登入驗證 (Auth Guard) | 
