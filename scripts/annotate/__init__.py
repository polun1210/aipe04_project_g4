"""AI 雙盲標註工具（issue 02）。

    uv run python -m scripts.annotate run      對每張照片分別請 Claude Code 與 Codex CLI 標註
    uv run python -m scripts.annotate compare  逐欄比對兩份標註，產出不一致清單、抽查名單、κ 與一致率
    uv run python -m scripts.annotate review   產生對照頁：左邊原圖、右邊要裁決與抽查的項目，填完匯出 CSV
    uv run python -m scripts.annotate stats    人工填完抽查名單與實際列數後，算抽查錯誤率並找出兩邊都漏掉列的照片

標註只含評分欄位（名稱、每份含量、單位、%、元素量、區塊、每一份量），不含範圍狀態與標準代碼：
那兩欄由名稱標準化規則決定，轉成標準答案時再依成分目錄填入，不讓 AI 猜。
"""
