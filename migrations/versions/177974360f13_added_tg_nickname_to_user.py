"""added tg_nickname to user

Revision ID: 177974360f13
Revises: e5cc3cb068cf
Create Date: 2025-05-14 15:16:25.768149

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel
import uuid


# revision identifiers, used by Alembic.
revision = '177974360f13'
down_revision = 'e5cc3cb068cf'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('tg_nickname', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    
    # Генерируем уникальные никнеймы для существующих пользователей
    connection = op.get_bind()
    users = connection.execute(sa.text("SELECT id FROM users")).fetchall()
    for user in users:
        nickname = str(uuid.uuid4())
        connection.execute(
            sa.text("UPDATE users SET tg_nickname = :nickname WHERE id = :user_id"),
            {"nickname": nickname, "user_id": user[0]}
        )
    
    # Делаем колонку not null после заполнения данными
    op.alter_column('users', 'tg_nickname', nullable=False)
    
    # Создаем уникальный индекс
    op.create_unique_constraint(None, 'users', ['tg_nickname'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'users', type_='unique')
    op.drop_column('users', 'tg_nickname')
    # ### end Alembic commands ###
