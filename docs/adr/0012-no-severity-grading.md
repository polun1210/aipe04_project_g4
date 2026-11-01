# 不做嚴重度分級

> 設計決策的參考紀錄，不是硬性規定；想調整請見 [README](README.md)。
> 取代 [ADR-0009](0009-rule-aggregation-max-severity-never-downgrade.md) 中「取最高等級」的部分。

2026-11-01 組長決定：**不做嚴重度分級**，規則與評估結果都不再有 `severity`。

## 理由

- 分級標準是組內自訂，沒有外部依據。
- 報告寫「優先處理」，等於替使用者做臨床判斷，違反 [ADR-0001](0001-output-claim-boundary.md) 的輸出邊界。
- 系統只說「有這個交互作用、出處在這裡」；嚴重程度交給醫師、藥師判斷。

## Consequences

- `Rule`、`RuleCandidate`、`Trigger`、`InteractionFinding` 與報告都沒有 `severity`。
- `Trigger` 帶規則的 `requires_professional_review`；`InteractionFinding.requires_professional_review` ＝ 任一 trigger 為 true。
- 同一成分的多條規則仍合成一筆 `InteractionFinding`，列出所有 triggers。
- **交互作用的排序**（計算層與模板共用）：
  1. `user_has_supplement = true` 的在前（使用者手上有東西可以處理）
  2. 同一組內依 `ingredients.csv` 的成分順序
- 摘要寫「這次有 N 項提醒」，第一個成分依上面的排序取第一個。
- 敘述檢查一律禁用「立即、立刻、馬上、緊急、危險、嚴重」（欄位 `strong_wording_violations`），提示詞與模板版本各加一版。
