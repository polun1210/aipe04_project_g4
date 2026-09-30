"""讀取建表組交付的 CSV，逐列以 Pydantic 模型驗證。

CSV 約定：UTF-8（可含 BOM）、第一列為欄位名、空白儲存格 ＝ null、陣列以 | 分隔。
"""

import csv
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


class CsvRowError(ValueError):
    def __init__(self, path: Path, line: int, error: ValidationError) -> None:
        super().__init__(f"{path.name} 第 {line} 列格式錯誤：\n{error}")


def load_csv(path: Path, model: type[M]) -> list[M]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    parsed: list[M] = []
    for line, row in enumerate(rows, start=2):  # 第 1 列是標題
        cleaned = {key: (value if value != "" else None) for key, value in row.items()}
        try:
            parsed.append(model.model_validate(cleaned))
        except ValidationError as error:
            raise CsvRowError(path, line, error) from error
    return parsed
