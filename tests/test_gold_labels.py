"""標準答案（tests/fixtures/labels/）必須永遠通過辨識草稿結構驗證，並和 sources.csv 對得上。"""

import csv
from pathlib import Path

import pytest

from app.schemas.label import ExtractionDraft

LABELS = Path(__file__).parent / "fixtures" / "labels"
GOLD = sorted(LABELS.glob("p*.json"))


@pytest.mark.parametrize("path", GOLD, ids=lambda p: p.stem)
def test_標準答案通過辨識草稿結構驗證(path):
    ExtractionDraft.model_validate_json(path.read_text(encoding="utf-8"))


def test_每份標準答案的照片都登記在來源清單():
    with (LABELS / "sources.csv").open(encoding="utf-8") as fh:
        registered = {row["image_id"] for row in csv.DictReader(fh)}
    for path in GOLD:
        draft = ExtractionDraft.model_validate_json(path.read_text(encoding="utf-8"))
        assert {s.image_id for s in draft.source_images} <= registered
