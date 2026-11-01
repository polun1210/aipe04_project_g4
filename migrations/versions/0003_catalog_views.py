"""catalog.v_* view：欄位名稱與型別對齊 app/schemas 的模型，後端只讀這些。

數值一律轉成 float8（模型是 float）；陣列用 ARRAY(子查詢) 並依 ord 排序；
view 本身 ORDER BY ord，還原 CSV 的列順序。

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

VIEWS = {
    "v_known_conditions": """
        SELECT condition_code, display_name_zh, backend_name, sort_order
        FROM catalog.known_conditions ORDER BY ord""",
    "v_drug_classes": """
        SELECT drug_class_code, display_name_zh, plain_description_zh, role, menu_group
        FROM catalog.drug_classes ORDER BY ord""",
    "v_drug_items": """
        SELECT i.active_ingredient_code, i.display_name_zh, i.english_name,
               ARRAY(SELECT c.drug_class_code FROM catalog.drug_item_classes c
                     WHERE c.active_ingredient_code = i.active_ingredient_code
                     ORDER BY c.ord) AS drug_class_codes,
               ARRAY(SELECT t.tradename FROM catalog.drug_tradenames t
                     WHERE t.active_ingredient_code = i.active_ingredient_code
                     ORDER BY t.id) AS common_tradenames_tw,
               ARRAY(SELECT d.condition_code FROM catalog.drug_item_conditions d
                     WHERE d.active_ingredient_code = i.active_ingredient_code
                     ORDER BY d.ord) AS related_conditions,
               i.requires_dose
        FROM catalog.drug_items i ORDER BY i.ord""",
    "v_drug_products": """
        SELECT p.name, p.lang,
               ARRAY(SELECT pi.active_ingredient_code FROM catalog.drug_product_ingredients pi
                     WHERE pi.product_id = p.product_id ORDER BY pi.ord) AS active_ingredient_codes,
               p.out_of_scope_ingredients
        FROM catalog.drug_products p ORDER BY p.product_id""",
    "v_drug_nutrient_doses": """
        SELECT active_ingredient_code, dose_option_mg::float8 AS dose_option_mg, nutrient_code,
               elemental_mg_per_unit::float8 AS elemental_mg_per_unit, source
        FROM catalog.drug_nutrient_doses ORDER BY ord""",
    "v_ingredients": """
        SELECT g.code, g.category, g.display_name_zh, g.standard_unit, g.accepted_units,
               ARRAY(SELECT s.synonym FROM catalog.ingredient_synonyms s
                     WHERE s.ingredient_code = g.code ORDER BY s.id) AS synonyms,
               g.ul_scope
        FROM catalog.ingredients g ORDER BY g.ord""",
    "v_out_of_scope_names": """
        SELECT name, note FROM catalog.out_of_scope_names ORDER BY ord""",
    "v_dris_values": """
        SELECT nutrient_code, sex, age_band, reference_type, reference_value::float8 AS reference_value,
               ul_value::float8 AS ul_value, unit
        FROM catalog.dris_values ORDER BY ord""",
    "v_compounds": """
        SELECT compound_code, nutrient_code, display_name_zh, synonyms, formula,
               ratio::float8 AS ratio, source
        FROM catalog.compounds ORDER BY ord""",
    "v_conversion_factors": """
        SELECT nutrient_code, from_unit, to_unit, factor::float8 AS factor, applies_to_form, source
        FROM catalog.conversion_factors ORDER BY id""",
    "v_rules": """
        SELECT r.rule_id, r.condition_type,
               COALESCE(r.drug_class_code, r.active_ingredient_code) AS condition_code,
               r.ingredient_code, r.ingredient_form_codes, r.interaction_type,
               r.requires_supplement_intake, r.requires_professional_review, r.advice_code,
               r.separation_hours::float8 AS separation_hours, r.reason_zh,
               ARRAY(SELECT rc.citation_id FROM catalog.rule_citations rc
                     WHERE rc.rule_id = r.rule_id ORDER BY rc.ord) AS citation_ids,
               r.evidence_tier, r.status, r.curated_by, r.reviewed_by, r.reviewed_at, r.curation_note
        FROM catalog.rules r ORDER BY r.ord""",
    "v_citations": """
        SELECT c.citation_id, d.source, c.source_record_id, d.url, c.section, c.quote, c.population,
               d.jurisdiction, d.retrieved_at, d.source_version, d.file_path AS document_path
        FROM catalog.citations c JOIN catalog.source_documents d USING (document_id)
        ORDER BY c.ord""",
}


def upgrade() -> None:
    for name, body in VIEWS.items():
        op.execute(f"CREATE VIEW catalog.{name} AS {body}")


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW catalog.{name}")
