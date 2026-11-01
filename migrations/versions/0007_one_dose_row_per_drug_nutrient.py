"""drug_nutrient_doses：同一個（成分、營養素）只能有一列。

計算層（app/assessing.py _drug_intakes）會把每一列都按劑量比例加進去，兩列就會重複計算。
真的需要多個劑量選項時，要先決定計算層怎麼挑列，再拿掉這個約束。

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog.drug_nutrient_doses "
        "ADD CONSTRAINT drug_nutrient_doses_one_row_per_nutrient UNIQUE (active_ingredient_code, nutrient_code)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE catalog.drug_nutrient_doses DROP CONSTRAINT drug_nutrient_doses_one_row_per_nutrient")
