"""每個 CHECK／外鍵約束至少一個「違反就寫不進去」的測試（資料庫自己擋錯）。"""

import psycopg
import pytest
from psycopg import errors

RULE = {
    "rule_id": "T-1", "condition_type": "drug_class", "drug_class_code": "ppi", "active_ingredient_code": None,
    "ingredient_code": "vitamin_b12", "ingredient_form_codes": [], "interaction_type": "drug_affects_nutrient",
    "requires_supplement_intake": False, "requires_professional_review": True, "advice_code": "inform_provider",
    "separation_hours": None, "reason_zh": "長期使用可能降低維生素 B12 的吸收", "evidence_tier": "t", "status": "draft",
    "curated_by": "甲", "reviewed_by": None, "reviewed_at": None, "curation_note": None, "ord": 999,
}  # fmt: skip


def _insert_rule(db: psycopg.Connection, **overrides) -> None:
    row = {**RULE, **overrides}
    version = db.execute("SELECT version FROM catalog.data_versions LIMIT 1").fetchone()[0]
    cols = [*row, "data_version"]
    db.execute(
        f"INSERT INTO catalog.rules ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        [*row.values(), version],
    )


def test_合法的規則寫得進去(db):
    _insert_rule(db)
    _insert_rule(db, rule_id="T-2", reason_zh="含 B12、D3 這類名稱的說明不算夾帶數字")


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"condition_type": "drug_ingredient"}, "條件寫成成分卻填了類別"),
        ({"drug_class_code": None, "active_ingredient_code": "atorvastatin"}, "條件寫成類別卻沒填類別"),
        ({"drug_class_code": None}, "兩個條件欄位都空"),
        ({"active_ingredient_code": "atorvastatin"}, "兩個條件欄位都填"),
        ({"requires_supplement_intake": True}, "沒補也提醒的規則被設成要補才提醒"),
        ({"interaction_type": "pharmacodynamic"}, "要補才提醒的規則被設成沒補也提醒"),
        ({"advice_code": "separate_timing"}, "錯開建議沒有時數"),
        ({"separation_hours": 2}, "有時數卻不是錯開建議"),
        ({"status": "reviewed", "reviewed_by": "甲", "reviewed_at": "2026-11-01"}, "自己審自己"),
        ({"status": "reviewed"}, "審定規則沒有覆核者"),
        ({"reason_zh": "每天最多 3 次"}, "說明文字夾帶數字"),
        ({"status": "approved"}, "不存在的狀態"),
    ],
)
def test_規則違反約束就寫不進去(db, overrides, why):
    with pytest.raises(errors.CheckViolation):
        _insert_rule(db, **overrides)


def test_規則指向不存在的成分或類別就寫不進去(db):
    with pytest.raises(errors.ForeignKeyViolation):
        _insert_rule(db, ingredient_code="no_such_nutrient")


def test_目標營養素沒有標準單位寫不進去(db):
    with pytest.raises(errors.CheckViolation):
        db.execute(
            "INSERT INTO catalog.ingredients (code, category, display_name_zh, ord) "
            "VALUES ('x_nutrient', 'target_nutrient', 'X', 99)"
        )


def test_允許成分可以沒有標準單位(db):
    db.execute(
        "INSERT INTO catalog.ingredients (code, category, display_name_zh, ord) "
        "VALUES ('x_allowed', 'allowed_ingredient', 'X', 99)"
    )


@pytest.mark.parametrize("ratio", [0, 1.5])
def test_元素比率不在零到一之間寫不進去(db, ratio):
    with pytest.raises(errors.CheckViolation):
        db.execute(
            "INSERT INTO catalog.compounds (compound_code, nutrient_code, display_name_zh, ratio, source, ord) "
            "VALUES ('bad', 'calcium', '壞', %s, 's', 99)",
            [ratio],
        )


def test_DRIs_上限為零寫不進去(db):
    with pytest.raises(errors.CheckViolation):
        db.execute("UPDATE catalog.dris_values SET ul_value = 0 WHERE nutrient_code = 'calcium'")


def test_同一族群重複兩個DRIs值寫不進去(db):
    with pytest.raises(errors.UniqueViolation):
        db.execute(
            "INSERT INTO catalog.dris_values (nutrient_code, sex, age_band, reference_type, reference_value, unit, ord) "
            "VALUES ('calcium', 'male', '19-30', 'ai', 1000, 'mg', 999)"
        )


def test_用藥類別的角色不在封閉列舉內寫不進去(db):
    with pytest.raises(errors.CheckViolation):
        db.execute("UPDATE catalog.drug_classes SET role = 'other' WHERE drug_class_code = 'ppi'")


def test_同一個同義詞不能屬於兩個成分(db):
    with pytest.raises(errors.UniqueViolation):
        db.execute("INSERT INTO catalog.ingredient_synonyms (ingredient_code, synonym) VALUES ('iron', '鈣')")


def test_使用者資料表的約束(db):
    db.execute("INSERT INTO app.users (user_id, google_sub) VALUES (gen_random_uuid(), 'sub-1')")
    with pytest.raises(errors.UniqueViolation):
        db.execute("INSERT INTO app.users (user_id, google_sub) VALUES (gen_random_uuid(), 'sub-1')")


def test_同一組換算條件不能有兩筆(db):
    # 計算層取第一筆符合的列，前提是營養素、原單位、目標單位、型態不重複
    with pytest.raises(errors.UniqueViolation):
        db.execute(
            "INSERT INTO catalog.conversion_factors (nutrient_code, from_unit, to_unit, factor, applies_to_form, source) "
            "VALUES ('vitamin_d', 'iu', 'ug', 0.03, 'all', '重複')"
        )


def test_同一個藥與營養素的劑量不能有兩列(db):
    # 計算層會把每一列都按劑量比例加進去，兩列就變兩倍
    with pytest.raises(errors.UniqueViolation):
        db.execute(
            "INSERT INTO catalog.drug_nutrient_doses "
            "(active_ingredient_code, dose_option_mg, nutrient_code, elemental_mg_per_unit, source, ord) "
            "VALUES ('magnesium_oxide', 500, 'magnesium', 301.6, '重複', 999)"
        )
