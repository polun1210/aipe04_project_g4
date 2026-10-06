# 協作方式

歡迎大家提出想法。以下是建議的流程，**不是硬性規定**，有更好的做法都可以提出來。

## 流程概覽

```
你的分支  ──發 PR──→  main（由組長合併）
```

1. **更新 main**

   ```bash
   git switch main
   git pull
   ```

2. **開自己的分支**，名稱用「模組/做什麼」，例如：

   ```bash
   git switch -c ocr/quality-check
   ```

   其他例子：`catalog/rules-ppi`、`frontend/verify-page`、`docs/prd-fix`。
   這樣組長從名稱就能看出這個分支在做什麼。

3. **做你的事**，想到就 commit，不用等做完。

4. **發 PR 前先檢查：**

   | 檢查 | 指令 | 說明 |
   |---|---|---|
   | 測試 | `uv run pytest` | **建議每個人都做**，看到全部通過（沒有 `failed`）就好 |
   | 程式檢查 | `uv run ruff check .` | 寫了 Python 程式的人建議做，只抓真正的錯誤。只改 CSV 或文件不需要 |

5. **push 並在 GitHub 開 PR。** 開 PR 時會自動帶出模板，照著填就好。記得填**驗收人**。
   如果動到 `app/schemas/`（資料格式）或想做的事與某份 ADR 不同，也請一併說明。

6. **組長 review 並合併。** 請不要直接 push 到 `main`。

---

## Commit 訊息

格式：`<類型>: <做了什麼>`，用繁體中文。

| 類型 | 用在 |
|---|---|
| `feat` | 新增功能 |
| `fix` | 修正錯誤 |
| `docs` | 文件、註解、README |
| `refactor` | 重構，行為不變 |
| `chore` | 環境設定、套件安裝、雜項 |

建議：

- 標題（第一行）不超過 25 個中文字，不加句號，用現在式
- 大多數情況只要標題就夠，不必勉強寫內文
- 寫「做了什麼」，不寫「改了哪些檔」
- 一個 commit 只做一件事
- 不確定要用哪個類型時，用 `chore`

例子：

```
feat: 新增影像品質檢查
fix: 修正鎂上限比對誤用平均值
docs: 補充使用者流程說明
chore: 新增 ruff 設定
```

---

## 其他常見情況

| 想做的事 | 看哪裡 |
|---|---|
| 改資料格式（JSON／CSV 的欄位） | [docs/schemas/README.md](docs/schemas/README.md)「想改格式怎麼辦」 |
| 想做的事和某份設計決策不同 | [docs/adr/README.md](docs/adr/README.md) |
| 加入新套件、環境出問題 | [docs/uv-guide.md](docs/uv-guide.md) |
