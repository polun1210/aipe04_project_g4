---
name: review-pr
description: 組長審組員 PR 的流程：抓到本機、跑檢查、對照工單／schemas／ADR、找 bug，最後產出中文留言草稿。使用時機：使用者說「審 PR #N」「review #N」或輸入 /review-pr N。也用於組員修改後的複審。
argument-hint: <PR 編號>
---

# 審組員的 PR

審核者是組長（唯一的 code owner）。你的角色是**先看第一輪、寫草稿**，判斷和對外動作都留給組長。

**沒有組長在對話中明確同意，不要做任何 GitHub 上的動作**：留言、review、approve、merge、改設定都算。

## 1. 收集資訊（先不要切分支）

```bash
gh pr view N --json title,body,author,baseRefName,headRefName,additions,deletions,files,commits,reviewDecision
gh pr checks N
gh pr list --state open --json number,title,baseRefName,headRefName
```

- **疊在一起的 PR**：如果 `baseRefName` 不是 `main`，或有其他 PR 的 base 是這個 PR 的 head 分支，就畫出相依關係，並在報告寫出合併順序。
- **大型 PR**（大約超過 1000 行）：先把檔案分成「程式碼」和「資料／fixtures／uv.lock」兩類，用一段話說明程式碼的部分在做什麼，細看的時候以程式碼為主。

## 2. 抓到本機

先用 `git status` 確認工作區是乾淨的，記下目前所在的分支，審完要切回去。

```bash
gh pr checkout N
```

**複審**（組員修改後又 push）時，改用 `git pull`，然後只看上次 review 之後的改動：

```bash
gh api repos/{owner}/{repo}/pulls/N/reviews --jq '.[-1].commit_id'
git diff <上次的 commit_id>..HEAD
```

## 3. 機器能檢查的

- CI 已經跑完的話，看 `gh pr checks N` 的結果就好
- CI 還沒跑或沒有 CI，就在本機跑：`uv sync --locked`、`uv run pytest`、`uv run ruff check .`
- 測試數量要和 PR 說明寫的一致

## 4. 對照規格

| 檢查什麼 | 去哪裡看 |
|---|---|
| 有沒有做到工單要求 | `notes/團隊四週進度表.md`（只在組長本機，沒有就跳過，並在報告註明） |
| 交接格式 | `app/schemas/`、`docs/schemas/README.md`、`docs/schemas/examples/` |
| 設計決策 | `docs/adr/` |
| 協作規範 | `CONTRIBUTING.md`、`.github/pull_request_template.md` |

特別注意：
- **程式和 schema 說的不一樣**：不只看欄位，docstring 寫的約定也要對（例如位置框的座標系）。這類交接約定的衝突，一律列為「必須改」。
- **改了 `app/schemas/`**：對應的範例檔有沒有一起改？PR 說明有沒有寫影響到誰？改名或刪除欄位要先在群組講過。
- **引用查不到的文件**（例如只存在作者自己 spec 裡的編號）：請作者附上連結或摘要。
- **PR 模板**：驗收人、驗收方式有沒有填？新增套件的話，`uv.lock` 有沒有一起 commit？
- **不該進 repo 的東西**：`.env`、金鑰、有版權的標示照片、大型二進位檔。

## 5. 找 bug

讀過 diff 裡的每個程式檔。重點放在會讓串接的人出錯的地方：函式簽名、錯誤處理、邊界情況、假版本和正式版本行為不一致的地方。

## 6. 報告格式

用以下格式回覆組長：

1. **檢查結果表**：測試、ruff、工單、改動範圍、PR 模板
2. **判斷**：分成三級，每一點附 `檔案:行號`
   - **必須改**：合併前要處理
   - **建議討論**：可以之後再定，但要說明為什麼現在提出
   - **小問題**：不擋合併
3. **合併注意事項**：合併順序、合併方式（見下方）
4. **留言草稿**：寫進 scratchpad 的 `prN-review.md`，同時貼在回覆裡

留言草稿的語氣：
- 組員多半是初學者，先講做得好的地方
- 每一點都說明「為什麼」以及「改成怎樣算好」
- 「必須改」寫成明確的要求，「建議討論」寫成提問

## 7. 組長同意之後

| 動作 | 指令 |
|---|---|
| 要求修改 | `gh pr review N --request-changes --body-file <草稿>` |
| 只留言 | `gh pr review N --comment --body-file <草稿>` |
| 核准 | `gh pr review N --approve` |

**合併方式**（等驗收人留言「驗收通過」後，由組長在 GitHub 上合併）：
- 一般 PR：Squash and merge
- 有其他 PR 疊在上面：用 **Create a merge commit**。用 squash 的話，上面那些 PR 會出現重複的改動，作者還得自己 rebase
- repo 有開「合併後自動刪分支」，疊在上面的 PR 會自動把 base 改成 `main`

審完要切回原本的分支。
