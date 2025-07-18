"""add_onupdate_cascade_to_warehouse_tables

Revision ID: ab5ee04c06de
Revises: 35ee93120cf9
Create Date: 2025-06-20 12:08:05.121436

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = 'ab5ee04c06de'
down_revision = '35ee93120cf9'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('sale_sku_fkey', 'sale', type_='foreignkey')
    op.create_foreign_key(None, 'sale', 'product', ['sku'], ['sku'], onupdate='CASCADE', ondelete='CASCADE')
    op.drop_constraint('stock_sku_fkey', 'stock', type_='foreignkey')
    op.create_foreign_key(None, 'stock', 'product', ['sku'], ['sku'], onupdate='CASCADE', ondelete='CASCADE')
    op.drop_constraint('transfer_sku_fkey', 'transfer', type_='foreignkey')
    op.create_foreign_key(None, 'transfer', 'product', ['sku'], ['sku'], onupdate='CASCADE', ondelete='CASCADE')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'transfer', type_='foreignkey')
    op.create_foreign_key('transfer_sku_fkey', 'transfer', 'product', ['sku'], ['sku'], ondelete='CASCADE')
    op.drop_constraint(None, 'stock', type_='foreignkey')
    op.create_foreign_key('stock_sku_fkey', 'stock', 'product', ['sku'], ['sku'], ondelete='CASCADE')
    op.drop_constraint(None, 'sale', type_='foreignkey')
    op.create_foreign_key('sale_sku_fkey', 'sale', 'product', ['sku'], ['sku'], ondelete='CASCADE')
    # ### end Alembic commands ###
