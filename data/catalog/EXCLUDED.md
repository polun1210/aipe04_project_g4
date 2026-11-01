# 明確排除的規則（不草擬）

規則只在 NIH ODS 專業版／NCCIH 原文**逐字支持**時才建。以下組合查過原文檔（`data/sources/`）後找不到支持，所以不建規則。
日後取得新的原文再重新評估。查證日期：2026-11-01（v1 範圍清單 `docs/v1-scope-checklist.md` 有列、但參考版沒有的組合）。

- **胰島素 × 鉀（鉀 ↓）**：`Potassium-HealthProfessional.md` 的「Interactions with Medications」只列 ACEI／ARB、保鉀利尿劑、
  loop／thiazide 利尿劑，沒有胰島素。全文提到 insulin 的地方只有糖尿病風險的觀察研究，不是藥物交互作用。
- **胰島素 × 鎂（鎂 ↓）**：`Magnesium-HealthProfessional.md` 的 insulin 只出現在糖尿病與鎂代謝的段落，
  「Interactions with Medications」沒有胰島素。
- **ACEI／ARB × 鋅（鋅 ↓）**：`Zinc-HealthProfessional.md` 的 ACE inhibitors 只出現在參考文獻標題，內文只支持 thiazide（已有規則）。
- **H2 受體拮抗劑 × 鐵（鐵吸收 ↓）**：`Iron-HealthProfessional.md` 只談質子幫浦抑制劑（已有規則），沒有提到 H2 受體拮抗劑。
- **含鈣／含鎂制酸劑 × 鐵吸收**：`Iron-HealthProfessional.md` 的用藥交互作用沒有制酸劑；
  `Calcium-HealthProfessional.md`、`Magnesium-HealthProfessional.md` 提到制酸劑時只談成分含量與鎂中毒，不談鐵。
- **COX-2 選擇性抑制劑（celecoxib、etoricoxib）× 鐵**：已取得的 Celecoxib、Etoricoxib 仿單只在 PRECISION 試驗提到
  源自腸胃道的缺鐵性貧血，且 celecoxib 比 naproxen／ibuprofen 少；沒有支持「鐵流失」提醒的原文。
  傳統 NSAIDs 的腸胃出血證據不得直接套用到這一類。
- **COX-2 選擇性抑制劑 × 魚油 n-3**（出血加成）：兩種仿單都沒有提到魚油或 omega-3。
- **COX-2 選擇性抑制劑 × 維生素 E**（出血加成）：兩種仿單都沒有提到維生素 E，NIH ODS 維生素 E 專業版也沒有提到這一類藥。
  維生素 E 保留為目標營養素，只做超量檢查。

- **Thiazide 類利尿劑 × 鈣（鈣滯留 ↑）**：`Calcium-HealthProfessional.md` 全文沒有 thiazide 或 diuretic。
  這個機轉的原文在 `VitaminD-HealthProfessional.md`（thiazide 減少尿鈣排出，與維生素 D 補充劑併用可能高血鈣），
  已由 `thiazide-vitamin-d` 涵蓋，不另建鈣的規則。
- **Statin × 菸鹼素（肌病變加成）**：`Niacin-HealthProfessional.md` 的「Interactions with Medications」只有 isoniazid／pyrazinamide
  與降血糖藥兩節；statin 只出現在心血管試驗的討論（加菸鹼酸沒有額外保護、死亡率反而較高），沒有肌病變的敘述，不能支持這條規則。
- **SGLT2 抑制劑 × 鎂（鎂 ↑）**：`Magnesium-HealthProfessional.md` 全文沒有 SGLT2 或 gliflozin，查無原文，不建規則。
- **Metformin × 葉酸（證據較弱）**：`Folate-HealthProfessional.md` 全文沒有 metformin，「Interactions with Medications」
  列的是 dolutegravir、levothyroxine、lithium、quinolone、methotrexate、抗癲癇藥、sulfasalazine，查無原文，不建規則。
- **含鈣制酸劑（碳酸鈣等）的劑量**：第一版不收，`drug_nutrient_doses.csv` 只有氧化鎂，只有氧化鎂計入藥物來源的攝取量。

另有 5 條規則在 nutrition-agent 已退役（`rules.csv` 中 `status = retired`，不進入判定）：
PPI × 鈣、Atorvastatin × 維生素 D、Simvastatin × 維生素 D、雙胍類 × 菸鹼素、胰島素 × 菸鹼素；退役原因見各規則的 `curation_note`。
