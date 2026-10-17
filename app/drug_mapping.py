"""藥名對照（純函式）：使用者確認的藥名文字 → 目錄中的藥物品項。"""

import unicodedata

from app.schemas.case import SelectedDrug
from app.schemas.catalog import DrugItem
from app.schemas.enums import ScopeStatus


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _names_of(item: DrugItem) -> set[str]:
    names = [item.active_ingredient_code, item.display_name_zh, item.english_name, *item.common_tradenames_tw]
    return {_normalize(n) for n in names}


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
