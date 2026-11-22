"""add admin role to users"""

from alembic import op
import sqlalchemy as sa


revision = "0008_admin_role"
down_revision = "0007_ai_hall_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("role", sa.String(16), nullable=False, server_default="user"))
        batch_op.create_index("ix_users_role", ["role"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_role")
        batch_op.drop_column("role")
