# 規則表：語意說明

> **欄位結構以 `app/schemas/rules.py`（規則、出處）與 `catalog.py`（目錄）為準**，範例見 `docs/schemas/examples/catalog/`，
> 對照表見 `docs/schemas/README.md`。本檔**不列欄位清單**，只保留 Pydantic 表達不出來的內容：
> 規則怎麼被套用、聚合、輸出，以及各欄位背後的判定語意與待決事項。

第一版採單條件模型（ADR-0009），每條規則只綁「一個用藥類別或有效成分 → 一個成分 → 一個方向」，
組合在系統評估時由程式按成分聚合（ADR-0009），不由整理規則的人事先枚舉。

- 用藥類別（`drug_class`）：**16 類**，見 `docs/v1-scope-checklist.md` §1
- 成分：13 項目標營養素 ＋ 3 項允許成分（ADR-0007）
- 慢性病（`known_conditions`）：5 種，**不觸發任何規則**，只用於報告涵蓋聲明與健康族群揭露
- 第一版規則數預估：**約 25–28 條**（含明確排除的記錄）

**凍結時程**：PRD 定版時同步凍結。

相關決策：ADR-0001（輸出宣稱邊界）、ADR-0002（DRIs 為唯一營養標準錨）、
ADR-0006（外部資料只用來事先整理成表）、ADR-0007（交互作用規則可引用少量非目標營養素成分）、
ADR-0009（聚合取最高等級，永不降級）。

---

## 一、結構總覽

```
known_conditions ── 只用於涵蓋聲明與健康族群揭露，不連到 rules

drug_classes ────┐
drug_items ──────┴─ condition_code ──→ rules ── citation_ids ──→ citations
                                          │
                                          │ ingredient_code
                                          ▼
                              ingredients（範圍內成分目錄，含 3 項允許成分）
```

資料怎麼來、系統怎麼用（ADR-0006）：

```
【事先整理（組員）】                          【系統評估時】
DRIs 本文 / NIH ODS / 仿單 …
        ↓ 依建表規範審核
候選 → 通過 → rules 一列 + citations          藥名對照得到的範圍內有效成分與所屬類別
        ↓ 雙人覆核                              ＋ 已核對的補充劑資料
status = reviewed  ──────────────────────→  查表 → 按成分聚合 → findings

TFDA 藥品資料 ──匯出有效許可證──→ 藥名表 ──→  藥包藥名 → 有效成分 → 範圍狀態
                                             （只查這些表，不呼叫任何外部來源）
```

---

## 二、目錄的語意

### 慢性病（`known_conditions`）

使用者註冊時勾選的慢性病，**不由系統推論**。另有一個選項「以上皆無」，與五種慢性病互斥；慢性病為強制作答，
不存在「未作答」狀態。

**慢性病不觸發任何規則，也不過濾藥名對照**（見 §七），只有兩個作用：

1. **報告涵蓋範圍聲明**：固定列出本系統涵蓋哪五種慢性病
2. **健康族群揭露**：勾選任一慢性病時，揭露 DRIs 參考值適用於健康族群

### 用藥類別（`drug_classes`）

`role` 分兩種：`rule_bearing`（規則型：會觸發判定）與 `coverage_only`（覆蓋型：不觸發規則，
但藥名對照必須認得它，才能標為範圍內）。

### 有效成分（`drug_items`）

藥名對照的**目標是這一層**，規則多數綁在類別層。`related_conditions` 不用於過濾（見 §七）。
只有含鈣／含鎂制酸劑與軟便劑需要填劑量。

### 藥名表

藥包上印的可能是商品名、學名或中文名，所以要有一張表把這些名稱都對到有效成分。
這張表**事先從 TFDA 藥品資料匯出**，系統評估時只查表、不連 TFDA（ADR-0006）：

```
TFDA 有效製劑許可證（2026-10-14 快照，約 1.8 萬張）
   ├─ 中文品名、英文品名
   └─ 成分名稱（學名，含鹽類，例如 AMLODIPINE BESYLATE）
          ↓ 成分對照（人工，約 44 項：AMLODIPINE BESYLATE → amlodipine）
藥名表：名稱 → 有效成分（複方一對多）→ 範圍內／範圍外
```

- 只匯出有效許可證，已註銷的名稱（例如 Dichlotride）自動排除。
- 成分對得上 `drug_items` → 範圍內；對不上 → 範圍外；表裡完全找不到 → 無法確認。
- 快照版本跟著規則資料版本記錄，每份評估都知道用的是哪一版。

---

## 三、規則的語意

- **`condition_type`／`condition_code`**：`drug_class` 的規則，在使用者選到該類別下**任一**有效成分時觸發；
  只有出處明確限定單一成分時才用 `drug_ingredient`（例如 Metformin × B12）。
- **`ingredient_form_codes`**：空 ＝ 所有型態皆適用。**僅在出處明確區分型態時填寫。**
- **`requires_supplement_intake`**：是否需要使用者正在補充此成分才觸發。`drug_affects_nutrient` 為 `false`
  （沒補也列出，即「相關營養素」），其餘為 `true`。
- **`severity`**：`priority`（🔴）／`attention`（🟡）／`info`（🔵）。**判定條件由建表規範定義，目前待決。**
- **`requires_professional_review`**：報告是否針對此成分**建議使用者諮詢醫師、藥師或營養師**。
  不是指團隊內部的專業審查。
- **`reason_zh`**：經覆核的固定說明文字。LLM 敘述不得增加此處沒有的機轉或建議。不得含任何數字。
- **`separation_hours`**：僅 `advice_code = separate_timing` 時填寫，數值必須出自本規則引用的出處。
- **`citation_ids`**：至少一筆，且**不可只有 SUPP.AI**（ADR-0006）。
- **`evidence_tier`**：由建表規範定義，**目前待決**。
- **`status`**：`draft`／`reviewed`／`retired`。**系統評估時只讀 `reviewed`。**
- **`curated_by`／`reviewed_by`**：建表者與覆核者須為不同人。

「接近上限」也是 ADR-0001 的判定結果，但它由補充劑來源攝取量與 DRIs 上限**計算**得出，
不是規則表中的一列。

**不存在「關注偏低」**：系統不判定、不提示不足（ADR-0001）。

---

## 四、出處的語意

- 出處若含建議量數字，數字**不得**進入 `reason_zh` 或報告（ADR-0002：數值錨只有 DRIs）。
- `supp_ai` 的出處只能作為**查漏的輔助**，單獨不足以成立一條規則（ADR-0006）。
- `quote` 以能支持本規則的最短原文段落為限。
- `population` 是此出處適用的族群（例如「長期服用 Metformin 者」），**與 DRIs 族群不同時必須標明**。

---

## 五、允許成分（ADR-0007）

允許成分在 `ingredients.csv` 中以 `category = allowed_ingredient` 標示，第一版共 3 項：

| `code` | 中文 | 撐住的規則 |
|---|---|---|
| `red_yeast_rice` | 紅麴 | × Statin → 重複用藥（monacolin K 即 lovastatin） |
| `glucosamine` | 葡萄糖胺 | 處方葡萄糖胺 vs 市售 → 重複使用（這是一條規則，不是已移除的重複補充軸） |
| `omega_3` | 魚油 n-3 | × COX-2 選擇性抑制劑 → 出血加成 🔍 待驗證 |

> **這三項成分通常不在營養標示方框內，而在成分欄。**
> 標示辨識的範圍必須涵蓋成分欄，否則三條規則全部無法命中。

已評估後排除的候選（纈草、褪黑激素、卡瓦、維生素 K）見 `docs/v1-scope-checklist.md` §3。
其後果是**慢性失眠症在第一版沒有任何規則**，該疾病的兩個用藥類別皆為覆蓋型。

---

## 六、建議行動（`advice_code`）的封閉列舉

ADR-0001 禁止輸出建議劑量、停用或購買建議。建議行動只能從下列值中選：

| 值 | 報告文案方向 | 適用 `interaction_type` |
|---|---|---|
| `separate_timing` | 與此藥錯開服用時間 | `absorption`，且出處有明確間隔 |
| `inform_provider` | 回診或領藥時，告知醫師或藥師你正在服用此補充劑 | 全部 |
| `consult_before_combining` | 與此藥併用前，先與醫師或藥師討論 | `pharmacodynamic` 等 |

**不存在也不得新增**「停用」「減量」「改吃某產品」這類值。
各值的正式使用條件隨建表規範一併定案。

---

## 七、系統評估時的查表與聚合

### 7.0 使用者的用藥輸入

```
藥包照片（一批可多張；沒有用藥可略過）
        ↓ VLM 辨識
藥包原文藥名
        ↓ 藥名對照（查藥名表；複方一對多）
有效成分 ＋ 藥物範圍狀態（範圍內／範圍外／無法確認）
        ↓ 使用者校對（可改、可新增，改了就重新對照）
送出評估 → 沒改名沿用後端存的草稿對照，改過名重新對照（前端送來的對照結果不採用）
        ↓
範圍內的有效成分 → 對映 drug_class_code → 進入 §7.1
範圍外／無法確認 → 不進規則判斷，只進報告揭露
```

**慢性病不得過濾藥名對照。** 使用者可能吃胃藥而不覺得那是「慢性病」，
也可能吃 Metformin 卻沒勾糖尿病。

### 7.1 查表

```
輸入（CaseProfile）：
  drugs         對照後的藥（或「沒有提供用藥」）；只取 scope_status = in_scope 的
  supplements   已核對的產品（VerifiedProduct）
  conditions    ★只用於涵蓋聲明與健康族群揭露，不進入下面的比對★

active = 範圍內藥物的有效成分 ∪ 其所屬的用藥類別
for condition in active:
    for rule in rules where rule.condition_code = condition and rule.status = reviewed:
        matched = 產品中 standard_code = rule.ingredient_code 的成分
                  （只看 scope_status = in_scope 的成分；
                    若 rule.ingredient_form_codes 非空，型態也須符合）
        if rule.requires_supplement_intake and not matched:
            continue
        產出 hit（rule, user_has_supplement = matched 是否非空）
```

劑量不進入規則判定：只判有無。

### 7.2 聚合（ADR-0009）

```
for ingredient in hits 中出現的所有成分:
    severity                     = max(該成分所有 hit 的 severity)
    requires_professional_review = any(該成分所有 hit 的 requires_professional_review)
    triggers                     = 該成分所有 hit 的條件與規則清單
```

**永不降級**：沒有任何資料能降低另一條規則的等級。

---

## 八、評估輸出

每個成分一筆、已聚合的結果，欄位見 `assessment.py` 的 `InteractionFinding`。

**findings 不含任何攝取量數值。** 規則類的判定只判有無；攝取量、建議總攝取量、上限這三個數值
由評估層依 ADR-0001 另行呈現（`RelevantNutrient`），不經過 findings，避免 LLM 把數字與規則說明混寫成劑量建議。
`separation_hours` 是 findings 中唯一允許的數字。

### 報告固定揭露的內容（`Disclosures`）

- 本系統涵蓋的慢性病、用藥類別與營養素（報告固定列出）
- 使用者是否勾選「以上皆無」、是否略過藥包辨識
- 範圍外的藥：以中性語氣列為「不在本系統評估範圍」
- 無法確認的藥：寫明「無法判斷是否有交互作用」
- 使用者勾選任一慢性病時，須揭露 DRIs 參考值適用於健康族群
- 有非每日服用的產品時，須揭露峰值假設同日服用
- 範圍外成分：以中性語氣列為「不在本系統評估範圍」
- 無法確認的成分：以警示語氣列為「系統無法確認，未納入檢查」
- 台灣常見但第一版未納入用藥類別的藥物（DPP-4 抑制劑、磺醯脲類、傳統 NSAIDs、抗凝血與抗血小板藥、骨鬆用藥）：
  報告固定列出，避免使用者誤以為涵蓋範圍完整。使用者實際吃的範圍外藥物，另依上面的規則逐一列出
- 未計入藥品來源的營養素（鈣、鎂、鐵）：除含鈣／含鎂制酸劑外皆不取得藥品劑量，此事實必須揭露

### 固定文案約束

- 勾「以上皆無」時寫「你未勾選本系統涵蓋的 5 種慢性病」，**不得**寫「你沒有疾病」
- 略過藥包辨識時寫「你沒有提供用藥資料」，**不得**寫「你沒有用藥」
- 慢性病寫「你勾選了〇〇」，不得寫成確診
- 沒有命中規則 ≠ 沒有風險，報告不得出現「未發現問題」「安全」等字樣
- `healthy_population_caveat = true` 時，報告須寫明建議攝取量與上限攝取量為健康族群的參考值

### ⚪「資料不足」的語意

⚪ **不以配對或條件為單位**，只用於：

1. 無法確認的成分（`unresolved_ingredients`）：「以下成分系統無法確認，未納入檢查」
2. 報告層級的固定免責：列出涵蓋範圍，說明範圍外的疾病、藥物或成分請諮詢醫師或藥師

---

## 九、Schema 層的自動檢查

以下規則不需人工檢查，違規條數必須為 0。

| 規則 | 目前的強制方式 |
|---|---|
| `interaction_type = drug_affects_nutrient` ⟺ `requires_supplement_intake = false` | ✅ `Rule` 內建驗證 |
| `separation_hours` 非空 ⟺ `advice_code = separate_timing` | ✅ `Rule` 內建驗證 |
| `reason_zh` 不含任何數字（`separation_hours` 由模板插入，不寫死在文字中） | ✅ `Rule` 內建驗證 |
| `curated_by ≠ reviewed_by`（`reviewed` 規則另須有覆核者與覆核日期） | ✅ `Rule` 內建驗證 |
| 每條規則至少一筆出處，且 `quote` 非空 | ✅ `citation_ids` 與 `quote` 的長度限制 |
| 規則引用的每個 `citation_id` 都存在於出處表 | ✅ `tests/test_schema_examples.py`（目前只檢查範例檔） |
| 每條 `reviewed` 規則至少一筆**非 `supp_ai`** 出處 | ⏳ 規則已定，**尚無自動檢查** |

---

## 十、待決事項對本 schema 的影響

| 待決事項 | 影響的欄位 | 狀態 |
|---|---|---|
| 建表規範（證據採納、分級、嚴重度、建議行動、是否建議諮詢） | `evidence_tier`、`severity`、`advice_code`、`requires_professional_review` | **待提出。建表開工前必須定稿，不可與建表並行** |
| ADR-0007 允許成分清單 | §五 | 3 項已提名，**待組長正式核准** |
| COX-2 選擇性抑制劑的兩條規則是否成立 | `rules`（鐵 ↓、× 魚油 n-3／維生素 E 出血加成） | 🔍 整理規則時依 Celecoxib／Etoricoxib 仿單驗證。不成立須以「明確排除」記錄理由 |
| 維生素 E 的去留 | 目標營養素清單 | 取決於上一列。若 COX-2 兩條皆不成立，維生素 E 將失去唯一藥物錨點 |
| 藥品來源攝取量的呈現 | `drug_nutrient_doses.csv`、`RelevantNutrient.intake_from_drugs` | 含鈣／含鎂制酸劑與軟便劑已追加劑量欄位；暫採與補充劑分開呈現。**v4 藥人工校對頁沒有劑量欄位，劑量從哪裡取得待決** |
