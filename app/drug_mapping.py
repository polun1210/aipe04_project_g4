"""藥名對照（純函式）：使用者確認的藥名文字 → 目錄中的藥物品項。"""

import unicodedata
from functools import lru_cache

from app.catalog_source import CatalogSource, get_catalog_source
from app.schemas.case import SelectedDrug
from app.schemas.catalog import DrugItem
from app.schemas.drug_label import DrugCandidate, DrugDraftRow
from app.schemas.enums import ScopeStatus
from app.schemas.reference import DrugProduct


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


class DrugProductIndex:
    """TFDA 品名（約 4 萬筆）的正規化索引：啟動時建一次，查詢時完全相符走 dict。"""

    def __init__(self, products: list[DrugProduct], rule_ingredients: frozenset[str] = frozenset()) -> None:
        # 有「以成分觸發」的規則（condition_type = drug_ingredient）的成分代碼，複方挑代表成分時優先
        self.rule_ingredients = rule_ingredients
        self._by_name: dict[str, DrugProduct] = {}
        for product in products:
            self._by_name.setdefault(_normalize(product.name), product)

    def get(self, name: str) -> DrugProduct | None:
        return self._by_name.get(_normalize(name))

    def containing(self, key: str) -> list[tuple[str, DrugProduct]]:
        """正規化後的品名包含 key 的品項（key 已正規化）；回 (正規化品名, 品項)。"""
        return [(n, p) for n, p in self._by_name.items() if key in n]


@lru_cache(maxsize=4)
def drug_product_index_of(catalog: CatalogSource) -> DrugProductIndex:
    rules = catalog.load_reference().rules
    rule_ingredients = frozenset(r.condition_code for r in rules if r.condition_type == "drug_ingredient")
    return DrugProductIndex(catalog.load_drug_products(), rule_ingredients)


def get_drug_product_index() -> DrugProductIndex:
    """FastAPI 依賴：跟著預設的目錄來源走，索引只建一次。"""
    return drug_product_index_of(get_catalog_source())


def _raw_names_of(item: DrugItem) -> list[str]:
    return [item.active_ingredient_code, item.display_name_zh, item.english_name, *item.common_tradenames_tw]


def same_drug_name(a: str, b: str) -> bool:
    """全形半形、大小寫、前後空白不同都算同一個名字。"""
    return _normalize(a) == _normalize(b)


def _names_of(item: DrugItem) -> set[str]:
    return {_normalize(n) for n in _raw_names_of(item)}


def map_drug_name(
    name: str,
    drug_items: list[DrugItem],
    dose_mg: float | None = None,
    times_per_day: int | None = None,
    products: DrugProductIndex | None = None,
) -> SelectedDrug:
    """先比對每個品項的代碼、中文名、英文名、台灣常見商品名；沒命中再用品名查 TFDA 品名表。

    都要完全相等才算命中。品項命中 → in_scope，從目錄複製代碼、中文名、類別。
    品名表命中：有範圍內成分 → in_scope（複方取第一個成分當代碼，類別取所有成分的聯集，
    因為 SelectedDrug 只放得下一個成分）；成分全部範圍外 → out_of_scope。都沒命中 → unresolved。
    劑量（來自 ConfirmedDrug）原樣帶過去。
    """
    key = _normalize(name)
    item = next((i for i in drug_items if key in _names_of(i)), None)
    if item is None:
        product = products.get(name) if products else None
        if product is not None:
            return _from_product(name, product, drug_items, products, dose_mg, times_per_day)
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
    products: DrugProductIndex | None = None,
) -> SelectedDrug:
    """送出評估時的藥名對照。

    使用者沒改藥名（跟草稿原文一樣）→ 沿用辨識時的對照：辨識時有商品名、學名可以比，
    比只拿整串原文完全比對準（「立普妥膜衣錠 10毫克」整串對不到，但商品名「立普妥」對得到）。
    草稿的對照也是後端算的，不是前端送來的。
    改過名、自己新增的列、草稿找不到、或草稿是「無法確認」→ 用 map_drug_name 重新對照。
    """
    if draft_row is None or not same_drug_name(name, draft_row.raw_name):
        return map_drug_name(name, drug_items, dose_mg, times_per_day, products)
    if draft_row.scope_status is ScopeStatus.OUT_OF_SCOPE:
        return SelectedDrug(
            raw_name=name, scope_status=ScopeStatus.OUT_OF_SCOPE, dose_mg=dose_mg, times_per_day=times_per_day
        )
    item = next((i for i in drug_items if i.active_ingredient_code == draft_row.active_ingredient_code), None)
    if item is None:  # 無法確認，或目錄已經沒有這個品項
        return map_drug_name(name, drug_items, dose_mg, times_per_day, products)
    return _in_scope(name, item, dose_mg, times_per_day)


def _representative(items: list[DrugItem], drug_items: list[DrugItem], rule_ingredients: frozenset[str]) -> DrugItem:
    """複方挑一個成分代表（SelectedDrug 只放一個成分）。

    (a) 目錄有成分組合完全相同的複方品項（代碼以 _ 拆開的集合相同）→ 用它；
    (b) 否則優先選有「以成分觸發」規則的成分；(c) 都沒有取第一個。
    """
    codes = {i.active_ingredient_code for i in items}
    if len(codes) > 1:
        combo = next((i for i in drug_items if set(i.active_ingredient_code.split("_")) == codes), None)
        if combo is not None:
            return combo
    return next((i for i in items if i.active_ingredient_code in rule_ingredients), items[0])


def _from_product(
    name: str,
    product: DrugProduct,
    drug_items: list[DrugItem],
    index: DrugProductIndex,
    dose_mg: float | None,
    times_per_day: int | None,
) -> SelectedDrug:
    by_code = {i.active_ingredient_code: i for i in drug_items}
    items = [by_code[c] for c in product.active_ingredient_codes if c in by_code]
    if not items:
        status = ScopeStatus.OUT_OF_SCOPE if product.out_of_scope_ingredients else ScopeStatus.UNRESOLVED
        return SelectedDrug(raw_name=name, scope_status=status, dose_mg=dose_mg, times_per_day=times_per_day)
    rep = _representative(items, drug_items, index.rule_ingredients)
    classes = list(dict.fromkeys(c for i in items for c in i.drug_class_codes))
    return SelectedDrug(
        raw_name=name,
        scope_status=ScopeStatus.IN_SCOPE,
        active_ingredient_code=rep.active_ingredient_code,
        display_name_zh=rep.display_name_zh,
        drug_class_codes=classes,
        dose_mg=dose_mg,
        times_per_day=times_per_day,
    )


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


def find_candidates(
    name: str,
    drug_items: list[DrugItem],
    limit: int = 10,
    drug_class_code: str | None = None,
    products: DrugProductIndex | None = None,
) -> list[DrugCandidate]:
    """名稱（代碼、中文名、英文名、商品名、TFDA 品名）包含輸入字串的品項；一個品項只出現一次。

    有給 drug_class_code 時先只留該類別的品項，再取前 limit 筆（不是取完再過濾）。
    完全相等的排最前面，其餘依中文名排序。輸入是空字串時回空清單。
    TFDA 品名命中時，該品名的每個範圍內成分各算一個候選，matched_name 是命中的品名。
    """
    key = _normalize(name)
    if not key:
        return []
    by_code = {i.active_ingredient_code: i for i in drug_items}
    hits: dict[str, tuple[bool, DrugItem, str]] = {}
    for item in drug_items:
        matched = next((n for n in _raw_names_of(item) if key in _normalize(n)), None)
        if matched is None:
            continue
        exact = key in _names_of(item)
        if exact:
            matched = next(n for n in _raw_names_of(item) if _normalize(n) == key)
        hits[item.active_ingredient_code] = (exact, item, matched)
    if products is not None:
        for normalized, product in products.containing(key):
            for code in product.active_ingredient_codes:
                item = by_code.get(code)
                if item is None:
                    continue
                exact = normalized == key
                if code not in hits or (exact and not hits[code][0]):
                    hits[code] = (exact, item, product.name)
    ranked = sorted(hits.values(), key=lambda h: (not h[0], h[1].display_name_zh))
    if drug_class_code is not None:
        ranked = [h for h in ranked if drug_class_code in h[1].drug_class_codes]
    return [
        DrugCandidate(
            active_ingredient_code=item.active_ingredient_code,
            display_name_zh=item.display_name_zh,
            english_name=item.english_name,
            matched_name=matched,
            drug_class_codes=item.drug_class_codes,
        )
        for _, item, matched in ranked[:limit]
    ]
