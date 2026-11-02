"""add idempotent legacy game import key"""
from alembic import op
import sqlalchemy as sa


revision = "0005_legacy_game_import"
down_revision = "0004_game_engine_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.add_column(sa.Column("legacy_id", sa.String(200), nullable=True))
        batch_op.create_unique_constraint("uq_game_user_legacy_id", ["user_id", "legacy_id"])


def downgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.drop_constraint("uq_game_user_legacy_id", type_="unique")
        batch_op.drop_column("legacy_id")
