"""藥名對照（純函式）：使用者確認的藥名文字 → 目錄中的藥物品項。"""

import unicodedata

from app.schemas.case import SelectedDrug
from app.schemas.catalog import DrugItem
from app.schemas.drug_label import DrugCandidate, DrugDraftRow
from app.schemas.enums import ScopeStatus


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _raw_names_of(item: DrugItem) -> list[str]:
    return [item.active_ingredient_code, item.display_name_zh, item.english_name, *item.common_tradenames_tw]


def _names_of(item: DrugItem) -> set[str]:
    return {_normalize(n) for n in _raw_names_of(item)}


def map_drug_name(
    name: str,
    drug_items: list[DrugItem],
    dose_mg: float | None = None,
    times_per_day: int | None = None,
) -> SelectedDrug:
    """依序比對每個品項的代碼、中文名、英文名、台灣常見商品名，完全相等才算命中。

    命中 → in_scope，從目錄複製代碼、中文名、類別；沒命中 → unresolved。
    目前還沒有「已知但範圍外」的藥名表，所以這一版產生不出 out_of_scope；
    藥名同義詞表進來後，命中表內但不在 16 類的藥標為 out_of_scope。
    劑量（來自 ConfirmedDrug）原樣帶過去。
    """
    key = _normalize(name)
    item = next((i for i in drug_items if key in _names_of(i)), None)
    if item is None:
        return SelectedDrug(
            raw_name=name,
            scope_status=ScopeStatus.UNRESOLVED,
            dose_mg=dose_mg,
            times_per_day=times_per_day,
        )
    return _in_scope(name, item, dose_mg, times_per_day)


def map_confirmed_drug(
    name: str,
    draft_row: DrugDraftRow | None,
    drug_items: list[DrugItem],
    dose_mg: float | None = None,
    times_per_day: int | None = None,
) -> SelectedDrug:
    """送出評估時的藥名對照。

    使用者沒改藥名（跟草稿原文一樣）→ 沿用辨識時的對照：辨識時有商品名、學名可以比，
    比只拿整串原文完全比對準（「立普妥膜衣錠 10毫克」整串對不到，但商品名「立普妥」對得到）。
    草稿的對照也是後端算的，不是前端送來的。
    改過名、自己新增的列、草稿找不到、或草稿是「無法確認」→ 用 map_drug_name 重新對照。
    """
    if draft_row is None or _normalize(name) != _normalize(draft_row.raw_name):
        return map_drug_name(name, drug_items, dose_mg, times_per_day)
    if draft_row.scope_status is ScopeStatus.OUT_OF_SCOPE:
        return SelectedDrug(
            raw_name=name, scope_status=ScopeStatus.OUT_OF_SCOPE, dose_mg=dose_mg, times_per_day=times_per_day
        )
    item = next((i for i in drug_items if i.active_ingredient_code == draft_row.active_ingredient_code), None)
    if item is None:  # 無法確認，或目錄已經沒有這個品項
        return map_drug_name(name, drug_items, dose_mg, times_per_day)
    return _in_scope(name, item, dose_mg, times_per_day)


def _in_scope(name: str, item: DrugItem, dose_mg: float | None, times_per_day: int | None) -> SelectedDrug:
    return SelectedDrug(
        raw_name=name,
        scope_status=ScopeStatus.IN_SCOPE,
        active_ingredient_code=item.active_ingredient_code,
        display_name_zh=item.display_name_zh,
        drug_class_codes=item.drug_class_codes,
        dose_mg=dose_mg,
        times_per_day=times_per_day,
    )


def find_candidates(name: str, drug_items: list[DrugItem], limit: int = 10) -> list[DrugCandidate]:
    """名稱（代碼、中文名、英文名、商品名）包含輸入字串的品項；一個品項只出現一次。

    完全相等的排最前面，其餘依中文名排序，最多 limit 筆。輸入是空字串時回空清單。
    """
    key = _normalize(name)
    if not key:
        return []
    hits: list[tuple[bool, DrugItem, str]] = []
    for item in drug_items:
        matched = next((n for n in _raw_names_of(item) if key in _normalize(n)), None)
        if matched is None:
            continue
        exact = key in _names_of(item)
        if exact:
            matched = next(n for n in _raw_names_of(item) if _normalize(n) == key)
        hits.append((exact, item, matched))
    hits.sort(key=lambda h: (not h[0], h[1].display_name_zh))
    return [
        DrugCandidate(
            active_ingredient_code=item.active_ingredient_code,
            display_name_zh=item.display_name_zh,
            english_name=item.english_name,
            matched_name=matched,
            drug_class_codes=item.drug_class_codes,
        )
        for _, item, matched in hits[:limit]
    ]
