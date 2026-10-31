"""persist opponent profile and custom search settings on games"""
from alembic import op
import sqlalchemy as sa


revision = "0004_game_engine_settings"
down_revision = "0003_email_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("engine_settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("games", "engine_settings")
