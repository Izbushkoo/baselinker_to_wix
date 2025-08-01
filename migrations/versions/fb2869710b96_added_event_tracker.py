"""added event tracker

Revision ID: fb2869710b96
Revises: 177974360f13
Create Date: 2025-06-11 17:11:50.077249

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision = 'fb2869710b96'
down_revision = '177974360f13'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('allegro_event_trackers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('last_event_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_allegro_event_trackers_token_id'), 'allegro_event_trackers', ['token_id'], unique=True)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_allegro_event_trackers_token_id'), table_name='allegro_event_trackers')
    op.drop_table('allegro_event_trackers')
    # ### end Alembic commands ###
