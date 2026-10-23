"""比對辨識草稿與使用者送出的校對結果，產生修正紀錄。辨識準確率的唯一來源。

保健食品（05b）：serving_info.<欄位> ／ nutrients.<row_id>.<欄位> ／ nutrients.<row_id>（整列刪除）
藥名（05c）：rows.<row_id>.name ／ rows.<row_id>（整列刪除）
使用者新增的列沒有 row_id，依送出順序記成 nutrients.new<n>／rows.new<n>（n 從 1 起算）。
"""

import json
from datetime import datetime
from enum import Enum
from uuid import UUID

from app.drug_mapping import same_drug_name
from app.schemas.case import ConfirmedDrug
from app.schemas.drug_label import DrugCorrection, DrugDraft
from app.schemas.enums import CorrectionType
from app.schemas.label import (
    ExtractionDraft,
    LabelCorrection,
    NutrientConfirmed,
    NutrientDraft,
    VerificationSubmission,
)

# 使用者在校對頁能改的欄位；raw_name、bbox 等原文資訊不能改，不比對
_NUTRIENT_FIELDS = ("standard_code", "scope_status", "nutrient_form_code", "per_serving", "unit", "stated_elemental_amount")
_SERVING_FIELDS = ("serving_size", "dose_unit")


class UnknownRowError(ValueError):
    def __init__(self, row_ids: list[str]) -> None:
        super().__init__(f"辨識草稿裡沒有這些列：{', '.join(row_ids)}")
        self.row_ids = row_ids


def label_corrections(
    draft: ExtractionDraft, submission: VerificationSubmission, product_id: UUID, corrected_at: datetime
) -> list[LabelCorrection]:
    draft_rows = {r.row_id: r for r in draft.nutrients}
    unknown = [n.row_id for n in submission.nutrients if n.row_id is not None and n.row_id not in draft_rows]
    if unknown:
        raise UnknownRowError(unknown)

    meta = draft.extraction_meta

    def record(path: str, kind: CorrectionType, before: object, after: object) -> LabelCorrection:
        return LabelCorrection(
            product_id=product_id,
            field_path=path,
            correction_type=kind,
            model_value=_text(before),
            corrected_value=_text(after),
            ocr_version=meta.ocr_version,
            rule_layer_version=meta.rule_layer_version,
            synonym_table_version=meta.synonym_table_version,
            corrected_at=corrected_at,
        )

    corrections = [
        record(f"serving_info.{f}", CorrectionType.MODIFIED, before, after)
        for f in _SERVING_FIELDS
        if (before := getattr(draft.serving_info, f)) != (after := getattr(submission.serving_info, f))
    ]
    added = 0
    for row in submission.nutrients:
        if row.row_id is None:
            added += 1
            corrections.append(record(f"nutrients.new{added}", CorrectionType.ADDED, None, _row_json(row)))
            continue
        original = draft_rows[row.row_id]
        corrections += [
            record(f"nutrients.{row.row_id}.{f}", CorrectionType.MODIFIED, before, after)
            for f in _NUTRIENT_FIELDS
            if (before := getattr(original, f)) != (after := getattr(row, f))
        ]
    kept = {n.row_id for n in submission.nutrients}
    corrections += [
        record(f"nutrients.{r.row_id}", CorrectionType.REMOVED, _row_json(r), None)
        for r in draft.nutrients
        if r.row_id not in kept
    ]
    return corrections


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, float | int):
        return str(float(value))
    return str(value)


def _row_json(row: NutrientConfirmed | NutrientDraft) -> str:
    values = {f: getattr(row, f) for f in _NUTRIENT_FIELDS}
    return json.dumps({k: v.value if isinstance(v, Enum) else v for k, v in values.items()}, ensure_ascii=False)


def drug_corrections(
    drafts: dict[UUID, DrugDraft], drugs: list[ConfirmedDrug], case_id: UUID, corrected_at: datetime
) -> list[DrugCorrection]:
    """drafts：這次送出有引用、而且後端找得到的藥包草稿。找不到的草稿（例如伺服器重啟過）就不比對。"""
    linked = [d for d in drugs if d.draft_id in drafts]
    unknown = [d.row_id for d in linked if d.row_id not in {r.row_id for r in drafts[d.draft_id].rows}]
    if unknown:
        raise UnknownRowError(unknown)

    def record(
        draft_id: UUID | None, path: str, kind: CorrectionType, before: str | None, after: str | None
    ) -> DrugCorrection:
        meta = drafts[draft_id].extraction_meta if draft_id else None
        return DrugCorrection(
            case_id=case_id,
            draft_id=draft_id,
            field_path=path,
            correction_type=kind,
            model_value=before,
            corrected_value=after,
            ocr_version=meta and meta.ocr_version,
            rule_layer_version=meta and meta.rule_layer_version,
            synonym_table_version=meta and meta.synonym_table_version,
            corrected_at=corrected_at,
        )

    corrections = []
    for d in linked:
        row = next(r for r in drafts[d.draft_id].rows if r.row_id == d.row_id)
        if not same_drug_name(d.name, row.raw_name):
            corrections.append(record(d.draft_id, f"rows.{d.row_id}.name", CorrectionType.MODIFIED, row.raw_name, d.name))
    added = [d for d in drugs if d.draft_id is None]
    corrections += [
        record(None, f"rows.new{n}", CorrectionType.ADDED, None, d.name) for n, d in enumerate(added, start=1)
    ]
    kept = {(d.draft_id, d.row_id) for d in linked}
    corrections += [
        record(draft_id, f"rows.{r.row_id}", CorrectionType.REMOVED, r.raw_name, None)
        for draft_id, draft in drafts.items()
        for r in draft.rows
        if (draft_id, r.row_id) not in kept
    ]
    return corrections
