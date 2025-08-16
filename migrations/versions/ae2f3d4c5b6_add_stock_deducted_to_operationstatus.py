"""add_stock_deducted_to_operationstatus

Revision ID: ae2f3d4c5b6
Revises: af835ec1d35a
Create Date: 2025-08-16 14:58:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'ae2f3d4c5b6'
down_revision = 'af835ec1d35a'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TYPE operationstatus ADD VALUE 'STOCK_DEDUCTED'")

def downgrade():
    # Note: PostgreSQL does not support removing enum values.
    pass