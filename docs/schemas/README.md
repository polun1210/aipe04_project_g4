# 第一版資料格式：對照與說明

這份說明讓你快速知道：系統裡有哪些 JSON、CSV，各自是什麼、從哪裡來、給誰用。

目前的格式是**第一版**，由後端先整理出來，目的是讓大家可以開工。
**覺得欄位不夠用、命名不順、或有更好的做法，都歡迎提出來討論**，怎麼改見文末。

---

## 資料怎麼流動

```
 ①目錄資料 CSV ──────→ 前端選單、後端
 ②規則表＋出處 CSV ──→ 後端規則引擎
 ③基本資料／疾病／用藥（前端表單）──→ 後端
 ④辨識草稿（標示辨識）──→ 核對介面
 ⑤核對後送出（核對介面）──→ 後端
 ⑥Assessment（後端）──→ 敘述層
 ⑦敘述輸出（敘述層）──→ 後端輸出檢查
 ⑧Report（後端）──→ 報告頁／PDF
```

**你只需要看跟你的模組有關的那幾個。** 箭頭從你的模組出發，代表你要**產出**這個格式；
箭頭指向你的模組，代表你會**收到**這個格式。其他的不用管。

---

## 有哪些檔案

範例都放在 `docs/schemas/examples/`，對應的規則寫在 `app/schemas/`（Pydantic 模型）。
所有範例都是同一個個案：72 歲男性、高血壓＋高血脂、5 種藥、3 罐保健食品。
**數值與規則命中都是示意**，不是覆核過的醫療結論。

### JSON：系統執行時流動的資料

| # | 範例檔 | 一句話 | 流向 | 對應模型 |
|---|---|---|---|---|
| ③ | `03_assessment_request` | 使用者按下「開始評估」送出的資料：年齡、性別、慢性病勾選、用藥勾選、要評估的產品 | 前端 → 後端 | `AssessmentRequest`（`case.py`） |
| ④ | `04a_extraction_accepted` | 使用者上傳照片後**立即**的回覆：工作編號，加上每張照片品質檢查是否通過 | 後端 → 前端 | `ExtractionAccepted`（`label.py`） |
| ④ | `04b_extraction_job_done` | 辨識**完成**後的結果：每份量、建議吃法、逐列成分（含座標） | 標示辨識 → 後端 → 核對介面 | `JobResponse[ExtractionDraft]`（`api.py`、`label.py`） |
| ⑤ | `05a_verification_submission` | 使用者核對、修正完後送出的資料（不含計算值） | 核對介面 → 後端 | `VerificationSubmission`（`label.py`） |
| ⑤ | `05b_label_corrections` | 後端比對「辨識草稿」與「使用者送出」後產生的**修正紀錄**（改前、改後），用來量測辨識準確率 | 後端內部 | `LabelCorrection`（`label.py`） |
| — | `case_profile` | **凍結的評估個案**：基本資料、用藥、所有已核對產品的完整快照，是計算層的唯一輸入 | 後端內部 | `CaseProfile`（`case.py`） |
| ⑥ | `06_assessment` | 計算層與規則引擎的結論：重複補充、營養素與上限、交互作用、揭露事項。等級與數字在這裡就確定 | 後端 → 敘述層 | `Assessment`（`assessment.py`） |
| ⑦ | `07_narration_output` | LLM 寫的白話說明，加上所用模型與 prompt 版本；先過輸出檢查才會進報告 | 敘述層 → 後端 | `NarrationOutput`（`narration.py`） |
| ⑧ | `08_report` | 最終報告：評估結果＋顯示名稱＋展開的出處＋通過檢查的敘述 | 後端 → 報告頁／PDF | `Report`（`report.py`） |
| — | `api_error` | 所有 API 失敗時的統一錯誤格式 | 後端 → 前端 | `ErrorResponse`（`api.py`） |

### CSV：建表資料（載入資料庫後供執行時查詢）

範例裡只有幾列示意資料；真實內容由建表填寫。CSV 的約定：UTF-8、第一列是欄位名、空白代表 null、陣列用 `|` 分隔。

| # | 範例檔（`catalog/`） | 一句話 | 誰讀取 | 對應模型 |
|---|---|---|---|---|
| ① | `known_conditions` | 5 種慢性病的勾選框文字與後端名稱 | 前端選單 | `KnownCondition` |
| ① | `drug_classes` | 16 個用藥類別，含白話說明與選單分組 | 前端選單、規則引擎 | `DrugClass` |
| ① | `drug_items` | 有效成分目錄：中英文名、所屬類別、台灣常見商品名（使用者勾選的是這一層） | 前端選單 | `DrugItem` |
| ① | `drug_nutrient_doses` | 含鈣／含鎂制酸劑的劑量選項，與換算成元素量的數值 | 計算層 | `DrugNutrientDose` |
| ① | `ingredients` | 16 個範圍內成分（13 項目標營養素＋3 項允許成分）：代碼、標準單位、同義詞、上限適用範圍 | 辨識標準化、核對介面選單 | `Ingredient` |
| ① | `out_of_scope_names` | 已知的範圍外名稱（熱量、蛋白質…），命中就標為範圍外 | 辨識標準化 | `OutOfScopeName` |
| ① | `dris_values` | DRIs 數值：營養素 × 性別 × 年齡組 → 建議量與上限 | 計算層 | `DrisValue` |
| ① | `compound_ratios` | 化合物的元素量比率（例如檸檬酸鈣 → 鈣 0.21） | 計算層 | `CompoundRatio` |
| ① | `conversion_factors` | 單位與型態換算（IU → µg 等） | 計算層 | `ConversionFactor` |
| ② | `rules` | 規則表：用藥類別 → 成分 → 方向，含嚴重度、建議行動、說明、覆核狀態 | 規則引擎 | `Rule`（`rules.py`） |
| ② | `citations` | 出處：來源、原文摘錄、適用族群、地區、版本 | 規則引擎、報告 | `Citation`（`rules.py`） |

①的模型都在 `catalog.py`。想看懂整條流程：先讀 `case_profile.json` 裡最短的一罐（紅麴膠囊），
再到 `06_assessment.json` 找紅麴出現在哪裡。看懂一筆資料怎麼流下去，其他都是同一個模式。

---

## 哪一頁 → 哪個網址 → 用哪個範例檔

頁面編號對應 `wireframe_v3` 的 PG-xxx。網址前綴一律是 `/api`；失敗時一律回 `api_error` 格式。
「狀態」欄：**已完成**＝已經能呼叫；**草案**＝後端打算這樣做，待跟前端確認後才動工；**之後**＝這一階段不做，先留位置。

### 第一週：手動輸入流程（不經照片辨識）

| 頁面 | 動作 | 方法與網址 | 送出 | 收到 | 狀態 |
|---|---|---|---|---|---|
| PG-004 使用者輸入頁 | 載入慢性病、藥物選單 | `GET /api/catalog` | — | `CatalogResponse`（`catalog/` 底下 CSV 的內容） | 已完成 |
| PG-007 保健食品資訊確認頁 | 按「確認」存一罐產品 | `POST /api/products` | `05a_verification_submission` | `product_id`（之後送評估時用），HTTP 201 | 已完成（計算為假版本） |
| PG-007 → PG-009 | 選「沒有其他保健食品」，開始評估 | `POST /api/assessments` | `03_assessment_request`（`product_ids` 放前面存好的產品） | `06_assessment` | 已完成（計算為假版本） |
| PG-010 報告呈現頁 | 顯示評估結果 | 同上一列的回傳 | — | `06_assessment` | 已完成（計算為假版本） |

PG-010 顯示「每天吃多少」「佔上限幾 %」，用 `06_assessment` 的 `relevant_nutrients`，每個營養素一筆：

| 要顯示 | 欄位 |
|---|---|
| 每天吃多少 | `peak_intake_from_supplements`（峰值）、`average_intake_from_supplements`（平均），單位看 `unit` |
| 上限數值 | `ul.ul_value` |
| 佔上限幾 % | `ul.ratio`（小數，前端乘 100；以峰值計算） |
| 是否超過上限 | `ul.exceeded` |

注意：`ul` 可能是 `null`（鉀、維生素 B12 沒有上限），前端要先判斷再讀；`basis` 是 `estimated` 時畫面要標「推估」；措辭依 `ul.phrasing`，不可自己寫「安全」。

### 之後的階段

| 頁面 | 動作 | 要用的範例檔 | 狀態 |
|---|---|---|---|
| PG-005／006 圖片上傳、辨識中 | 上傳照片、等辨識結果 | `04a_extraction_accepted`、`04b_extraction_job_done` | 之後 |
| PG-010 報告呈現頁、PG-014 歷史報告詳細資料頁 | 顯示完整報告（含白話敘述與出處） | `08_report` | 之後 |
| PG-013 報告記錄查詢頁 | 依日期範圍列出歷史報告 | 待定 | 之後 |
| PG-002／003／012 登入、註冊、設定 | 帳號管理 | 待定（昊昀負責） | 之後 |

第一週還沒有登入，後端先用固定的測試帳號（`user_id`）存資料。

---

## 哪些需要一致，哪些自己決定

**需要一致：上面這些檔案的欄位與代碼。**
它們是模組與模組之間的交接處，格式不同，資料就接不起來，所以先寫下來、用測試守住。

**各模組自己決定：只有一個模組用得到的東西。** 只要最後產出或收下的資料符合上面的檔案，裡面怎麼做都可以，例如：

- 資料庫的資料表怎麼設計
- 辨識模組內部的中間結果（例如 OCR 的原始輸出）
- LLM 的提示詞怎麼寫
- 前端內部的狀態管理
- 離線建表工具的中間產物（`rules.py` 裡的 `RuleCandidate` 只是參考格式，可依工具需要調整）

---

## 怎麼看範例與模型

**大多數時候，只要看範例 JSON 就夠了。** 讀的時候問三件事：有哪些欄位？值是什麼型態？哪些可以不填？

想知道「還能填什麼」或「為什麼被擋」時，才看 Pydantic 模型。只要認得四種寫法：

| 寫法 | 意思 |
|---|---|
| `欄位: 型態` | 必填 |
| `欄位: 型態 \| None = None` | 可以不填 |
| `Field(gt=0)`、`Field(min_length=1)` | 數值或長度的限制 |
| `@model_validator` 底下的中文錯誤訊息 | 跨欄位的規則，直接讀那句中文 |

型態是 `Sex`、`IngredientCode` 這類大寫開頭的名稱，代表是**選單**，可選的值在 `app/schemas/enums.py`。

**寫完怎麼檢查**（在專案根目錄執行，檔名和類別換成你的）：

```bash
uv run python -c "from app.schemas.label import ExtractionDraft; ExtractionDraft.model_validate_json(open('my_output.json', encoding='utf-8').read()); print('OK')"
```

印出 `OK` 就是格式正確。報錯時訊息會指出哪個欄位錯，例如 `nutrients.3.unit: Input should be 'mg', 'ug', …`。

**2026-09-29 起，欄位結構以 `app/schemas/` 為準。**
範例一定能通過模型驗證（`tests/test_schema_examples.py` 會檢查），所以範例和結構不會對不上。
`supplement-label-output.md`、`rule-table.md` 只放**語意說明**（為什麼這樣設計、怎麼計算、怎麼判定），不列欄位。

---

## 寫資料時的約定

這些約定是為了讓資料接得起來。如果哪一條讓你的模組很難做，請提出來一起看。

| 約定 | 說明 |
|---|---|
| 欄位名要完全一致 | 多一個欄位會被擋下，拼錯欄位名一下就看得出來 |
| 代碼用選單 | 成分、用藥類別、慢性病、單位…都是封閉選單（`enums.py`），不接受自由文字 |
| 單位用 ASCII | `mg`、`ug`、`mg_ate`、`mg_ne`、`iu`…，不用 µg、mcg；畫面上的「微克」由畫面轉換 |
| 代碼和顯示名稱分開 | 計算只用 `standard_code`；`display_name_zh` 只給人看 |
| `raw_name` 保留原文 | 辨識到的原始文字，留作稽核，不修改 |
| 成分列用 `row_id` 定位 | 不用陣列索引（刪掉一列後索引會錯位） |
| 範圍外成分沒有代碼 | `scope_status` 不是 `in_scope` 時，`standard_code` 一律是 null |
| 魚油 | EPA、DHA、魚油總量各一列，代碼都是 `omega_3`，用 `nutrient_form_code` 區分 |
| 計算值由後端算 | 元素量、每日攝取量、上限比例一律由後端計算，前端送來的不會被採用 |
| findings 不放攝取量 | `interactions` 裡唯一允許的數字是 `separation_hours` |
| 峰值與平均 | 上限比對一律用 peak；重複補充兩個合計都存（ADR-0005） |
| 「以上皆無」 | 一律用 `{selected: [...], none_selected: bool}`，兩者互斥、必須作答 |

---

## 各檔案目前的穩定程度

讓你知道哪些可以放心依賴、哪些可能還會調整。

| 標記 | 意思 |
|---|---|
| ✅ 穩定 | 欄位不太會改名或刪除，可以放心依賴 |
| ➕ 可能新增 | 可能新增欄位，但不會動到既有欄位 |
| ⏳ 有待決事項 | 有一處尚未定案，見備註 |

| 檔案 | 狀態 | 備註 |
|---|---|---|
| `enums.py` | ✅ | |
| `common.py` | ✅ | |
| `catalog.py` | ⏳ | 化合物與型態（`nutrient_form_code`、`compound_code`）目前是自由字串，尚無對應的目錄；其餘穩定 |
| `rules.py` | ✅ | `severity`、`evidence_tier` 的「值」待建表規範，欄位本身不受影響 |
| `case.py` | ✅ | |
| `label.py` | ➕ | 成分名稱對映的來源標記等欄位，待 10/5 決定 |
| `assessment.py` | ⏳ | `DuplicateFinding`：範圍外成分的重複偵測方式待定，`ingredient_code` 目前必填，是唯一可能改型別的地方 |
| `narration.py` | ➕ | 敘述所需的證據素材若有調整，只會新增欄位 |
| `report.py` | ⏳ | `ReportDuplicate` 繼承 `DuplicateFinding`，隨它變動；其餘穩定 |
| `api.py` | ✅ | |
| `csv_io.py` | ✅ | |

**結構已定、值還沒定（不影響開工）**

| 項目 | 欄位 |
|---|---|
| 嚴重度判定條件、證據等級 | `Rule.severity`、`Rule.evidence_tier` |
| 規則內容、出處原文 | `rules.csv`、`citations.csv` |
| DRIs 數值、化合物比率、制酸劑元素量 | `dris_values.csv`、`compound_ratios.csv`、`drug_nutrient_doses.csv` |
| 有效成分目錄（約 44 項） | `drug_items.csv` |
| COX-2 規則與維生素 E 去留 | 規則表 |

---

## 想改格式怎麼辦

**歡迎提出，不用覺得問題太小。** 不確定該不該動的時候，先在群組或 Issue 講一聲，通常比先改省事。

如果想直接動手：

1. 改 `app/schemas/` 的模型，同時改對應的範例檔
2. 跑 `uv run pytest`，確認全綠
3. 發 PR，由組長合併

| 想做的事 | 怎麼處理 |
|---|---|
| **新增欄位** | 直接發 PR 即可 |
| **改名或刪除欄位** | 請先在群組講一聲，因為可能會影響到用它的模組 |
