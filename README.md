# 補對了嗎？— AI 個人化營養補充評估系統

年長者（以及協助他們的家人、朋友）告知自己的慢性病與用藥，並上傳正在服用的保健食品包裝照片，
系統檢查補充劑有沒有**重複補充、接近上限、跟用藥相衝**，並給出方向性的改善建議。

這個 repo 收的是大家已有共識的資訊：**產品說明、資料格式、設計決策，以及開發環境**。
各模組怎麼做，由負責的人自己決定。

---

## 快速開始

```bash
git clone <專案網址>
cd <專案資料夾>
uv sync            # 安裝環境（第一次需要先裝 uv，見 docs/uv-guide.md）
uv run pytest      # 看到 passed、沒有 failed，就表示環境沒問題
```

---

## 想知道什麼，看哪裡

| 想知道 | 看 |
|---|---|
| 這個系統做什麼、給誰用、使用者怎麼走一遍 | [docs/prd.md](docs/prd.md) |
| 某個詞是什麼意思 | [CONTEXT.md](CONTEXT.md) |
| 支援哪些藥、營養素、成分 | [docs/v1-scope-checklist.md](docs/v1-scope-checklist.md) |
| 各模組之間傳什麼資料（JSON／CSV） | [docs/schemas/README.md](docs/schemas/README.md) |
| 哪一頁打哪個網址、送什麼收什麼（前後端對接） | [docs/schemas/README.md](docs/schemas/README.md#哪一頁--哪個網址--用哪個範例檔) |
| 為什麼這樣設計 | [docs/adr/README.md](docs/adr/README.md) |
| 怎麼安裝環境、加套件 | [docs/uv-guide.md](docs/uv-guide.md) |
| 怎麼協作、發 PR、commit 怎麼寫 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| DRIs 資料有哪些要注意的地方 | [docs/dris-reference-notes.md](docs/dris-reference-notes.md) |

**不知道從哪開始：先讀 [docs/prd.md](docs/prd.md)，再看 [docs/schemas/README.md](docs/schemas/README.md) 裡跟你的模組有關的那幾個檔案。**

---

## 專案結構

```
app/schemas/          所有 JSON／CSV 的資料格式（Pydantic 模型）
tests/                自動檢查：範例與格式規則有沒有被破壞
docs/
  prd.md              產品需求文件
  schemas/            資料格式的說明與範例
  adr/                設計決策紀錄
  v1-scope-checklist.md
  dris-reference-notes.md
  uv-guide.md
CONTEXT.md            術語表
DRIs_Table.md         DRIs 第八版總表的轉檔（參考資料）
DRIs_Full.md          DRIs 第八版完整本文的轉檔（參考資料）
```
