# 營養標示：語意說明

> **欄位結構以 `app/schemas/label.py`（Pydantic）為準**，範例見 `docs/schemas/examples/`，對照表見 `docs/schemas/README.md`。
> 本檔**不列欄位清單**，只保留 Pydantic 表達不出來的內容：資料如何流動、關鍵欄位的語意、計算規則、
> 換算與上限適用性、多圖聯集規則、給評估層的保證。

**命名公約**（跨模組一致）：
- `raw_*` ＝ 影像上的原始文字，未經處理
- `standard_*` ＝ 標準化後的值
- 沒有前綴者 ＝ 系統計算產生的值

---

## 一、資料如何流動

```
④ ExtractionDraft         辨識草稿：只放「標示上寫了什麼」，不做任何換算
        ↓  使用者核對
⑤ VerificationSubmission  核對後送出：不含任何計算欄位
        ↓  後端重算（單位換算、元素量、每日攝取量）
   VerifiedProduct        完整產品，凍結進評估個案
```

計算欄位（元素量、每日攝取量、`ul_applicable`…）只由後端產生；前端送來的一律不採信。
未通過核對的產品不會成為 `VerifiedProduct`，因此不會進入評估。

---

## 二、關鍵欄位的語意

- **`serving_size`**：每份的**劑型單位數**（一份 ＝ 2 粒，就是 2.0），不是重量。它是所有攝取量計算的分母，
  算錯分母，後面全錯，所以核對時必填。
- **`raw_name`**：標示原文，之後任何人都不可修改，留作稽核。使用者新增的列沒有 `raw_name`。
- **`standard_code`**：名稱標準化在使用者核對**之前**完成；使用者只能從成分目錄的封閉選單重選，不接受自由輸入。
- **`percent_dv`**：每日參考值百分比，**只顯示，不是劑量**。它存在的目的，是讓核對介面能把它和劑量欄分開，
  避免把百分比讀成劑量。
- **`scope_status`** 三態：

  | 值 | 意思 |
  |---|---|
  | `in_scope` | 對映到目標營養素或允許成分，進入評估 |
  | `out_of_scope` | 知道是什麼，但不在評估範圍（如熱量、Q10） |
  | `unresolved` | 系統無法確認是什麼，使用者核對時也選了「無法確定」 |

  非 `in_scope` 的成分，`standard_code` 一律為 `null`，但仍保留該列，讓校對畫面與照片一致，報告也能誠實列出。
- **魚油**：EPA、DHA、魚油總量各一列，`standard_code` 都是 `omega_3`，用 `nutrient_form_code` 區分。
- **允許成分**（紅麴、葡萄糖胺、魚油 n-3，ADR-0007）：只判有沒有，不做數值判定。
  它們通常寫在**成分欄，不在營養標示方框內**，因此標示辨識的範圍必須涵蓋成分欄，否則對應的規則全部無法命中。
- **元素量**：`elemental_basis` 記錄來源（`label_stated`／`estimated`／`unknown`／`not_applicable`）。
  `estimated` 一律要在報告中揭露為推估（ADR-0004）。標示有載明元素量時填 `stated_elemental_amount`，
  三種常見寫法的填法見 `label.py` 中該欄位的註解。

---

## 三、計算規則

```
                     frequency_type
                           │
         ┌─────────────────┴─────────────────┐
         ▼                                   ▼
   units_per_day_peak              units_per_day_average
   = times_per_day × amount_per_time      （依頻率攤平）
         │                                   │
         └────────────── ÷ serving_size ─────┘
                           ▼
              servings_per_day_peak / _average
                           │
                           × amount_per_serving_standard
                           ▼
              peak_daily_amount / average_daily_amount
```

| `frequency_type` | `units_per_day_peak` | `units_per_day_average` |
|---|---|---|
| `daily` | `times_per_day × amount_per_time` | 同 peak |
| `alternate_days` | `times_per_day × amount_per_time` | peak ÷ 2 |
| `weekly_n_times` | `times_per_day × amount_per_time` | peak × `days_per_week` ÷ 7 |
| `cyclic_on_off` | `times_per_day × amount_per_time` | peak × on ÷ (on + off) |
| `as_needed` | `null` | `null`（`is_quantifiable = false`） |

**上限攝取量比對一律用 `peak_daily_amount`。** 兩值相同時報告不需區分；
不同時，措辭須為「你**服用當日**來自補充劑的攝取量已達上限的 X%」。

### 手算驗證

以一款綜合維他命軟糖為例（維生素 D 每份 10 µg）：

| 情境 | `serving_size` | `units_per_day_peak` | `servings_per_day_peak` | 維生素 D `peak_daily_amount` |
|---|---|---|---|---|
| 每天早晚各一顆 | 2.0 | 2.0 | **1.0** | 10 µg |
| 每天早晚各一顆 | 1.0 | 2.0 | **2.0** | 20 µg |
| 隔天吃兩顆 | 2.0 | 2.0 | 1.0（peak）／0.5（avg） | 10 µg（peak）／5 µg（avg） |
| 每週一三五各一包 | 1.0 | 1.0 | 1.0（peak）／0.43（avg） | 上限比對用 peak |

若用單一的「每日倍數」欄位，第一列會被誤寫成 2.0 或 1.0；分開記錄劑型單位與份數才能避免這種混淆。
完整的填值範例見 `docs/schemas/examples/case_profile.json`。

---

## 四、單位與型態換算

每條換算都必須記錄 `applies_to_form` 與 `source`，寫入該筆成分的 `conversion`。

| 營養素 | 標示單位 | 換算 | 適用型態 | 出處 |
|---|---|---|---|---|
| 維生素 D | IU | 1 IU = 0.025 µg | 全部 | DRIs 總表 `1μg = 40 I.U.` |
| 維生素 E | IU | 1 IU ≈ 0.67 mg α-TE | **全部型態** | DRIs 採 NRC 1989 的 α-TE 體系，IU 依生物活性定義，天然與合成型相同（見 `docs/dris-reference-notes.md`） |
| 維生素 E | mg | × 1.00 | d-α-生育醇 | NRC 1989（DRIs 維生素 E 章參考文獻 2），建表前回查原文 |
| 維生素 E | mg | × 0.91 | d-α-生育醇醋酸酯 | 同上 |
| 維生素 E | mg | × 0.74 | dl-α-生育醇 | 同上 |
| 維生素 E | mg | × 0.67 | dl-α-生育醇醋酸酯 | 同上 |
| 葉酸 | µg（合成葉酸） | × 1.7 → µg DFE | 合成葉酸，與食物同時攝取 | DRIs 本文 `DFE = 食物葉酸 + 1.7 × 人工合成葉酸`。**僅用於與建議量並列呈現**；上限比對不乘 1.7 |

型態只在**以毫克標示**時影響換算。化合物元素量的比率表另建（`compound_ratios.csv`，ADR-0004）。

### 上限適用性（`ul_applicable`）

依 DRIs 本文查核（`docs/dris-reference-notes.md`）：

| 營養素 | 計入上限比對的型態 | 不計入者 |
|---|---|---|
| 維生素 E | 全部型態 | — |
| 葉酸 | 合成葉酸，以 µg 直接比對 1000 µg | 甲基葉酸（5-MTHF）等型態：**待決** |
| 鎂 | 補充劑與**含鎂藥物**（非食物性鎂） | 食物來源 |
| 菸鹼素 | 🔍 菸鹼醯胺是否計入待查證（UL 以菸鹼酸潮紅訂定） | — |
| 鉀、維生素 B12 | 無 UL，不做上限比對 | 全部 |

**標示未寫型態時的預設假設**（必須明文，且報告須揭露該筆為假設）：

- 維生素 E 以毫克標示且未寫型態 → 假設為 d-α-生育醇（× 1.00）
- 葉酸未寫型態 → 假設為合成葉酸

兩條預設的方向一致：**上限比對不低估**。代價是可能高估，因此必須揭露。

---

## 五、多圖聯集規則

同一產品可上傳多張照片，聯集為一筆產品資料。去重鍵：`(standard_code, nutrient_form_code)`。
同鍵多筆時的來源優先序：

```
營養標示表 > 每粒/每份含量說明 > 原料名稱欄 > 正面行銷文案
```

`serving_info` 衝突（正面寫「每日 2 粒」、背面表格寫「每份 1 粒」）時，
**一律以營養標示表為準**；正面文案的數字視為建議吃法，寫入 `label_suggested_intake`。

所有衝突都必須在核對介面對使用者顯示，並記錄採用了哪張影像。

---

## 六、給評估層的保證

本模組交棒時保證：

1. 只有通過人工核對的產品才會成為 `VerifiedProduct` 進入評估，所有數值都經使用者確認
2. 同一 `standard_code` 的 `standard_unit` 全系統一致，可直接跨產品加總
3. `peak_daily_amount` 與 `average_daily_amount` 語意固定，不可互換用途
4. 允許成分（紅麴、葡萄糖胺、魚油 n-3）只判有無，不進入上限或攝取量判定；
   `ul_applicable = false` 的成分（含無 UL 的鉀、維生素 B12）不得進入上限比對
5. `elemental_basis = estimated` 的數值在報告中必須被揭露為推估（ADR-0004）
6. **`scope_status` 不是 `in_scope` 的成分不得進入定量判定與規則比對。**
   報告分兩個清單揭露：
   - `out_of_scope`（`Disclosures.out_of_scope_ingredients`）：寫「以下成分不在本系統評估範圍」（中性）
   - `unresolved`（`Disclosures.unresolved_ingredients`）：寫「以下成分系統無法確認，未納入檢查，如有疑慮請諮詢藥師」（警示）

   `unresolved` 可能是範圍內成分偽裝的，是漏報的來源，其比例同時作為名稱標準化的品質指標
