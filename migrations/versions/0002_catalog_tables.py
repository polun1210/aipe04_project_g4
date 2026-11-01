"""catalog 的表（20 張）與 CHECK 約束。

`ord` 欄位是匯入時的列順序（CSV 的順序），view 靠它還原順序，後端拿到的清單才會跟 CSV 版一樣。

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = """
CREATE TABLE catalog.data_versions (
    version text PRIMARY KEY,
    imported_at timestamptz NOT NULL DEFAULT now(),
    note text
);

CREATE TABLE catalog.known_conditions (
    condition_code text PRIMARY KEY,
    display_name_zh text NOT NULL,
    backend_name text NOT NULL,
    sort_order int NOT NULL,
    ord int NOT NULL
);

CREATE TABLE catalog.drug_classes (
    drug_class_code text PRIMARY KEY,
    condition_code text REFERENCES catalog.known_conditions,
    display_name_zh text NOT NULL,
    plain_description_zh text NOT NULL,
    role text NOT NULL CHECK (role IN ('rule_bearing', 'coverage_only')),
    menu_group text NOT NULL,
    ord int NOT NULL
);

CREATE TABLE catalog.ingredients (
    code text PRIMARY KEY,
    category text NOT NULL CHECK (category IN ('target_nutrient', 'allowed_ingredient')),
    display_name_zh text NOT NULL,
    standard_unit text,
    accepted_units text[] NOT NULL DEFAULT '{}',
    ul_scope text CHECK (ul_scope IN ('supplement_only', 'total_intake')),
    ord int NOT NULL,
    CHECK (category = 'allowed_ingredient' OR standard_unit IS NOT NULL)
);

CREATE TABLE catalog.ingredient_synonyms (
    id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingredient_code text NOT NULL REFERENCES catalog.ingredients,
    synonym text NOT NULL UNIQUE
);

CREATE TABLE catalog.drug_items (
    active_ingredient_code text PRIMARY KEY,
    display_name_zh text NOT NULL,
    english_name text NOT NULL,
    requires_dose boolean NOT NULL DEFAULT false,
    ord int NOT NULL
);

CREATE TABLE catalog.drug_item_classes (
    active_ingredient_code text NOT NULL REFERENCES catalog.drug_items,
    drug_class_code text NOT NULL REFERENCES catalog.drug_classes,
    ord int NOT NULL,
    PRIMARY KEY (active_ingredient_code, drug_class_code)
);

CREATE TABLE catalog.drug_item_conditions (
    active_ingredient_code text NOT NULL REFERENCES catalog.drug_items,
    condition_code text NOT NULL REFERENCES catalog.known_conditions,
    ord int NOT NULL,
    PRIMARY KEY (active_ingredient_code, condition_code)
);

CREATE TABLE catalog.drug_tradenames (
    id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    active_ingredient_code text NOT NULL REFERENCES catalog.drug_items,
    tradename text NOT NULL
);

CREATE TABLE catalog.drug_products (
    product_id int PRIMARY KEY,
    name text NOT NULL,
    lang text NOT NULL CHECK (lang IN ('zh', 'en')),
    out_of_scope_ingredients text[] NOT NULL DEFAULT '{}',
    UNIQUE (name, lang)
);

CREATE TABLE catalog.drug_product_ingredients (
    product_id int NOT NULL REFERENCES catalog.drug_products,
    active_ingredient_code text NOT NULL REFERENCES catalog.drug_items,
    ord int NOT NULL,
    PRIMARY KEY (product_id, active_ingredient_code)
);

CREATE TABLE catalog.drug_nutrient_doses (
    active_ingredient_code text NOT NULL REFERENCES catalog.drug_items,
    dose_option_mg numeric NOT NULL CHECK (dose_option_mg > 0),
    nutrient_code text NOT NULL REFERENCES catalog.ingredients,
    elemental_mg_per_unit numeric NOT NULL CHECK (elemental_mg_per_unit > 0),
    source text NOT NULL,
    ord int NOT NULL,
    PRIMARY KEY (active_ingredient_code, dose_option_mg, nutrient_code)
);

CREATE TABLE catalog.out_of_scope_names (
    name text PRIMARY KEY,
    note text,
    ord int NOT NULL
);

CREATE TABLE catalog.dris_values (
    nutrient_code text NOT NULL REFERENCES catalog.ingredients,
    sex text NOT NULL CHECK (sex IN ('male', 'female')),
    age_band text NOT NULL CHECK (age_band IN ('19-30', '31-50', '51-70', '71+')),
    reference_type text NOT NULL CHECK (reference_type IN ('rda', 'ai')),
    reference_value numeric NOT NULL CHECK (reference_value > 0),
    ul_value numeric,
    unit text NOT NULL,
    ord int NOT NULL,
    PRIMARY KEY (nutrient_code, sex, age_band),
    CHECK (ul_value IS NULL OR ul_value > 0)
);

CREATE TABLE catalog.compounds (
    compound_code text PRIMARY KEY,
    nutrient_code text NOT NULL REFERENCES catalog.ingredients,
    display_name_zh text NOT NULL,
    synonyms text[] NOT NULL DEFAULT '{}',
    formula text,
    ratio numeric NOT NULL CHECK (ratio > 0 AND ratio <= 1),
    source text NOT NULL,
    ord int NOT NULL
);

CREATE TABLE catalog.conversion_factors (
    id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nutrient_code text NOT NULL REFERENCES catalog.ingredients,
    from_unit text NOT NULL,
    to_unit text NOT NULL,
    factor numeric NOT NULL CHECK (factor > 0),
    applies_to_form text NOT NULL,
    source text NOT NULL
);

CREATE TABLE catalog.source_documents (
    document_id text PRIMARY KEY,
    source text NOT NULL,
    title text NOT NULL,
    url text,
    jurisdiction text NOT NULL,
    retrieved_at date NOT NULL,
    source_version text,
    file_path text NOT NULL
);

CREATE TABLE catalog.citations (
    citation_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES catalog.source_documents,
    section text,
    quote text NOT NULL CHECK (quote <> ''),
    population text NOT NULL,
    source_record_id text,
    ord int NOT NULL
);

CREATE TABLE catalog.rules (
    rule_id text PRIMARY KEY,
    condition_type text NOT NULL CHECK (condition_type IN ('drug_class', 'drug_ingredient')),
    drug_class_code text REFERENCES catalog.drug_classes,
    active_ingredient_code text REFERENCES catalog.drug_items,
    ingredient_code text NOT NULL REFERENCES catalog.ingredients,
    ingredient_form_codes text[] NOT NULL DEFAULT '{}',
    interaction_type text NOT NULL
        CHECK (interaction_type IN ('absorption', 'pharmacodynamic', 'drug_affects_nutrient')),
    requires_supplement_intake boolean NOT NULL,
    requires_professional_review boolean NOT NULL,
    advice_code text NOT NULL
        CHECK (advice_code IN ('separate_timing', 'inform_provider', 'consult_before_combining')),
    separation_hours numeric CHECK (separation_hours > 0),
    reason_zh text NOT NULL,
    evidence_tier text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft', 'reviewed', 'retired')),
    curated_by text NOT NULL,
    reviewed_by text,
    reviewed_at date,
    curation_note text,
    data_version text NOT NULL REFERENCES catalog.data_versions,
    ord int NOT NULL,
    CHECK ((condition_type = 'drug_class') = (drug_class_code IS NOT NULL)),
    CHECK ((drug_class_code IS NOT NULL) <> (active_ingredient_code IS NOT NULL)),
    CHECK ((interaction_type = 'drug_affects_nutrient') = (NOT requires_supplement_intake)),
    CHECK ((advice_code = 'separate_timing') = (separation_hours IS NOT NULL)),
    CHECK (status <> 'reviewed'
           OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND reviewed_by <> curated_by)),
    CHECK (reason_zh !~ '(^|[^A-Za-z0-9-])[0-9]')
);

CREATE TABLE catalog.rule_citations (
    rule_id text NOT NULL REFERENCES catalog.rules,
    citation_id text NOT NULL REFERENCES catalog.citations,
    ord int NOT NULL,
    PRIMARY KEY (rule_id, citation_id)
);

CREATE INDEX rules_data_version_idx ON catalog.rules (data_version);
CREATE INDEX drug_product_ingredients_item_idx ON catalog.drug_product_ingredients (active_ingredient_code);
"""


def upgrade() -> None:
    for statement in TABLES.split(";\n"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP SCHEMA catalog CASCADE")
    op.execute("CREATE SCHEMA catalog")
