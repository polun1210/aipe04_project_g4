"""標註的資料結構，以及交給 claude --json-schema 與 codex --output-schema 的 JSON Schema。

JSON Schema 手寫而不是由 Pydantic 產生：OpenAI 的結構化輸出（Codex 用）要求每個欄位都列在
required、可為 null 的欄位要寫成 ["number", "null"]、每層都要 additionalProperties: false，
Pydantic 產生的 schema 不符合。兩者是否一致由測試檢查。
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StrictModel
from app.schemas.enums import DoseUnit, LabelSection, Unit

PROMPT_VERSION = "a1"  # 改提示詞或結構就加版本，標註紀錄會跟著記


class AnnotatedRow(StrictModel):
    raw_name: str  # 名稱原文，括號內容一起照抄
    per_serving: float | None = Field(ge=0)  # 每份含量
    unit: Unit | None
    percent_dv: float | None = Field(ge=0)  # 每日參考值%
    stated_elemental_amount: float | None = Field(ge=0)  # 標示載明的元素量（規則同 NutrientDraft）
    label_section: LabelSection


class AnnotatedServing(StrictModel):
    serving_size: float | None = Field(gt=0)  # 劑型單位數，不是重量
    dose_unit: DoseUnit | None


class Annotation(StrictModel):
    serving: AnnotatedServing
    rows: list[AnnotatedRow]


class AnnotationRecord(StrictModel):
    """一個標註者對一張照片的標註，連同可追溯的執行資訊。"""

    image_id: str
    annotator: Literal["claude", "codex"]
    model: str  # 執行時以 --model 指定的模型
    models_reported: list[str] = Field(default_factory=list)  # 工具自己回報實際用到的模型（有的話）
    prompt_version: str
    annotated_at: datetime
    annotation: Annotation


def _nullable(json_type: str) -> dict:
    return {"type": [json_type, "null"]}


def _nullable_enum(enum: type) -> dict:
    return {"type": ["string", "null"], "enum": [e.value for e in enum] + [None]}


JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["serving", "rows"],
    "properties": {
        "serving": {
            "type": "object",
            "additionalProperties": False,
            "required": ["serving_size", "dose_unit"],
            "properties": {
                "serving_size": _nullable("number"),
                "dose_unit": _nullable_enum(DoseUnit),
            },
        },
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "raw_name",
                    "per_serving",
                    "unit",
                    "percent_dv",
                    "stated_elemental_amount",
                    "label_section",
                ],
                "properties": {
                    "raw_name": {"type": "string"},
                    "per_serving": _nullable("number"),
                    "unit": _nullable_enum(Unit),
                    "percent_dv": _nullable("number"),
                    "stated_elemental_amount": _nullable("number"),
                    "label_section": {"type": "string", "enum": [e.value for e in LabelSection]},
                },
            },
        },
    },
}

PROMPT = f"""\
請打開這個資料夾裡唯一的一張圖片 {{filename}}，只靠看圖，把台灣保健食品標示上的內容填入指定的 JSON 結構。
不要執行任何程式、不要做 OCR、不要上網、不要讀其他檔案。

規則：
1. 名稱一律逐字照抄原文（含括號與括號內的字），不翻譯、不改寫。看不清楚的數字填 null，不要猜。
2. rows：營養標示方框的每一列、每粒／每份含量說明的每一項、成分欄用頓號或逗號分開的每一項，各一列。
   - per_serving：「每份」那一欄的含量數字。同一列有「每份」與「每100公克」時只填每份。成分欄沒寫含量填 null。
   - unit：{", ".join(u.value for u in Unit)} 擇一。毫克＝mg、微克／μg／mcg＝ug、公克＝g、大卡＝kcal、
     IU＝iu、mg α-TE＝mg_ate、mg NE＝mg_ne；CFU、億等其他單位填 other；沒有含量填 null。
   - percent_dv：每日參考值百分比的數字（不含 %）。百分比絕對不可以填進 per_serving。
   - stated_elemental_amount（元素量，單位同 unit）：
     「檸檬酸鈣(含純鈣50mg) 238mg」→ per_serving 238、stated_elemental_amount 50；
     「鈣(碳酸鈣) 200mg」→ per_serving 200、stated_elemental_amount 200（數字本身就是元素量）；
     「檸檬酸鈣 2000mg」→ per_serving 2000、stated_elemental_amount null；
     沒寫化合物的成分（例如「鎂 100mg」「維生素D 10μg」）填 null。
   - label_section：nutrition_table＝營養標示方框；per_unit_note＝每粒／每份含量說明小字；
     ingredient_list＝成分欄；front＝正面行銷文案；other＝其他。
3. serving：「每一份量」。serving_size 是劑型單位數（每份 2 粒填 2），不是重量；
   dose_unit 從 {", ".join(d.value for d in DoseUnit)} 擇一（粒、顆要依外觀判斷是 capsule、tablet 還是 softgel）。
   照片上沒有「每一份量」就兩個都填 null。
"""
