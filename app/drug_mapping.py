"""藥名對照（純函式）：使用者確認的藥名文字 → 目錄中的藥物品項。"""

import unicodedata

from app.schemas.case import SelectedDrug
from app.schemas.catalog import DrugItem
from app.schemas.drug_label import DrugCandidate
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
