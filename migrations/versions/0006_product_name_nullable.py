"""app.products.product_name 允許空值：VerifiedProduct.product_name 在模型裡可以是 null。

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE app.products ALTER COLUMN product_name DROP NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE app.products SET product_name = '' WHERE product_name IS NULL")
    op.execute("ALTER TABLE app.products ALTER COLUMN product_name SET NOT NULL")
