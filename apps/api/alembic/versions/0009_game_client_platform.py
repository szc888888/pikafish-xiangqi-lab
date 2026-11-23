"""Record each game's creation platform; legacy games remain unknown."""

from alembic import op
import sqlalchemy as sa


revision = "0009_game_client_platform"
down_revision = "0008_admin_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.add_column(sa.Column("client_platform", sa.String(24), nullable=False, server_default="unknown"))


def downgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.drop_column("client_platform")
