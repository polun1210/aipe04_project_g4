"""app 的表（12 張）：使用者資料。users、health_profiles 先建好，A-3 才開始用。

jsonb 欄放凍結的快照（評估個案、判定結果、報告）與辨識草稿；要查詢的欄位拆成一般欄位。

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLES = """
CREATE TABLE app.users (
    user_id uuid PRIMARY KEY,
    google_sub text UNIQUE,
    email text,
    name text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.health_profiles (
    user_id uuid PRIMARY KEY REFERENCES app.users,
    birth_year int NOT NULL,
    birth_month int NOT NULL CHECK (birth_month BETWEEN 1 AND 12),
    sex text NOT NULL CHECK (sex IN ('male', 'female')),
    conditions_none boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.health_profile_conditions (
    user_id uuid NOT NULL REFERENCES app.health_profiles,
    condition_code text NOT NULL REFERENCES catalog.known_conditions,
    PRIMARY KEY (user_id, condition_code)
);

CREATE TABLE app.supplement_drafts (
    product_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app.users,
    draft jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.products (
    product_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app.users,
    product_name text NOT NULL,
    snapshot jsonb NOT NULL,
    verified_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.product_nutrients (
    product_id uuid NOT NULL REFERENCES app.products,
    row_id text NOT NULL,
    ingredient_code text REFERENCES catalog.ingredients,
    scope_status text NOT NULL,
    per_serving numeric,
    unit text,
    elemental_basis text,
    peak_daily_amount numeric,
    average_daily_amount numeric,
    PRIMARY KEY (product_id, row_id)
);

CREATE TABLE app.drug_drafts (
    draft_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app.users,
    draft jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.assessments (
    case_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app.users,
    created_at timestamptz NOT NULL DEFAULT now(),
    decision_data_version text NOT NULL REFERENCES catalog.data_versions,
    case_profile jsonb NOT NULL,
    assessment jsonb NOT NULL
);

CREATE TABLE app.assessment_products (
    case_id uuid NOT NULL REFERENCES app.assessments,
    product_id uuid NOT NULL REFERENCES app.products,
    PRIMARY KEY (case_id, product_id)
);

CREATE TABLE app.reports (
    report_id uuid PRIMARY KEY,
    case_id uuid NOT NULL UNIQUE REFERENCES app.assessments,
    user_id uuid NOT NULL REFERENCES app.users,
    generated_at timestamptz NOT NULL DEFAULT now(),
    report_date date NOT NULL,
    report jsonb NOT NULL
);

CREATE TABLE app.label_corrections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app.users,
    product_id uuid,
    correction jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.drug_corrections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES app.users,
    case_id uuid NOT NULL REFERENCES app.assessments,
    correction jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX products_user_idx ON app.products (user_id);
CREATE INDEX assessments_user_idx ON app.assessments (user_id, created_at);
CREATE INDEX assessments_version_idx ON app.assessments (decision_data_version);
CREATE INDEX reports_user_date_idx ON app.reports (user_id, report_date);
CREATE INDEX product_nutrients_ingredient_idx ON app.product_nutrients (ingredient_code);
"""


def upgrade() -> None:
    for statement in TABLES.split(";\n"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.execute("DROP SCHEMA app CASCADE")
    op.execute("CREATE SCHEMA app")
