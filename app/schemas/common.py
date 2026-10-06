"""跨模組共用的基底類別與小型別。"""

from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

T = TypeVar("T")


class StrictModel(BaseModel):
    """所有交接點模型的基底：多一個欄位就報錯，擋掉拼錯的欄位名與 LLM 多吐的欄位。"""

    model_config = ConfigDict(extra="forbid")


class FrozenModel(StrictModel):
    """凍結快照（評估個案、Assessment、Report）：建立後不可修改。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _split_pipe(value: Any) -> Any:
    """CSV 裡的陣列欄位以 | 分隔：「立普妥|冠脂妥」→ ["立普妥", "冠脂妥"]；空白 → []。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    return value


PipeList = Annotated[list[T], BeforeValidator(_split_pipe)]
"""JSON 裡是一般陣列；從 CSV 讀入時接受以 | 分隔的字串。"""


class BoundingBox(StrictModel):
    """整數像素。座標系 ＝ 依 EXIF 方向轉正後的圖；前端畫框要用轉正後的圖。"""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ExclusiveSelection(StrictModel, Generic[T]):
    """強制作答的多選題：勾具體項目，或勾「以上皆無」，兩者互斥，不存在未作答。"""

    selected: list[T] = Field(default_factory=list)
    none_selected: bool = False

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> "ExclusiveSelection[T]":
        if self.none_selected and self.selected:
            raise ValueError("勾了「以上皆無」就不能再勾其他項目")
        if not self.none_selected and not self.selected:
            raise ValueError("必須作答：勾選項目，或勾「以上皆無」")
        return self
