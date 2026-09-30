# uv 使用說明：環境與套件

這份說明怎麼用 uv 建立開發環境、跑測試、加入套件。

## uv 是什麼

uv 是管理 Python 環境的工具。一個指令就能裝好 Python 版本、虛擬環境和專案需要的所有套件，
而且每個人裝出來的版本都一樣，不會出現「在我電腦上是好的」。

---

## 第一次設定

**1. 安裝 uv**（只做一次，裝完請重開終端機）

- Windows（PowerShell）：

  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

- macOS／Linux：

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

完整說明見官方文件：<https://docs.astral.sh/uv/getting-started/installation/>

**2. 下載專案並安裝環境**

```bash
git clone <專案網址>
cd <專案資料夾>
uv sync
```

`uv sync` 會依 `.python-version` 使用 Python 3.12，建立 `.venv` 虛擬環境，並安裝專案需要的所有套件。
電腦上沒有 Python 3.12 時，uv 通常會自動下載；若失敗，執行 `uv python install 3.12`。

**3. 確認一切正常**

```bash
uv run pytest
```

看到 `passed`、沒有 `failed`，就表示環境沒問題。

---

## 日常指令

| 想做什麼 | 指令 |
|---|---|
| 讓環境與專案一致（拉了新的 main 之後） | `uv sync` |
| 執行測試 | `uv run pytest` |
| 執行 Python 程式 | `uv run python 檔名.py` |
| 檢查程式有沒有真正的錯誤（可選） | `uv run ruff check .` |
| 加入套件 | `uv add 套件名` |
| 移除套件 | `uv remove 套件名` |
| 確認環境與鎖檔一致 | `uv sync --locked` |

`uv run` 的意思是「在專案的環境裡執行」，所以不需要自己啟動虛擬環境。

---

## 兩個檔案：`pyproject.toml` 與 `uv.lock`

| 檔案 | 記錄什麼 | 誰修改 |
|---|---|---|
| `pyproject.toml` | 我們**需要什麼**：套件名稱與最低版本 | 用 `uv add`／`uv remove` 間接修改 |
| `uv.lock` | **實際裝了哪一版**，連同它依賴的所有套件 | uv 自動產生，不要手動編輯 |

**兩個檔案都要 commit。** 有了 `uv.lock`，每個人裝出來的版本才會完全一致。

目前 main 的套件很少：執行時需要 `pydantic`；開發用 `pytest` 和 `ruff`。
其他套件由各模組在自己的分支加入。

---

## 需要新套件時

1. 在自己的分支執行 `uv add 套件名`
2. 執行 `uv run pytest`，確認沒有弄壞既有的東西
3. 一起 commit `pyproject.toml` 和 `uv.lock`
4. 在 PR 說明這個套件用來做什麼、為什麼選它

組長合併時會看幾件事：授權條款、體積大小、Windows 和 Mac 是否都裝得起來。

### 很大、只有自己的模組用的套件

如果套件很大（例如影像處理相關），可以放在**獨立群組**，讓其他人不必安裝：

```bash
uv add --group ocr 套件名        # 加入名為 ocr 的群組（群組名稱自己取）
uv sync --group ocr              # 需要用它的人這樣安裝
```

⚠️ **注意：之後單純執行 `uv sync`，會把這個群組的套件移除。** 我實測過：`uv sync` 會讓環境與指定的群組完全一致。
所以使用群組的人，每次都要帶 `--group 群組名`。

這只是建議做法，不是規定。如果覺得麻煩，也可以直接 `uv add`，讓大家都安裝。

---

## 遇到問題

| 狀況 | 處理 |
|---|---|
| `uv.lock` 合併時衝突 | 不用自己解，請告訴組長 |
| Windows 終端機顯示亂碼（中文變成問號或怪字） | 在 PowerShell 執行 `$env:PYTHONUTF8 = "1"` 後再跑，只對這個視窗有效 |
| 找不到 Python 3.12 | 執行 `uv python install 3.12` |
| 不確定環境有沒有跟上 main | 執行 `uv sync`，再 `uv run pytest` |
