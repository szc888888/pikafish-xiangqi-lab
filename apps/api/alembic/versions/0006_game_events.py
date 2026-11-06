"""store undo and hint events with games"""
from alembic import op
import sqlalchemy as sa

revision = "0006_game_events"
down_revision = "0005_legacy_game_import"
branch_labels = None
depends_on = None

def upgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.add_column(sa.Column("events", sa.JSON(), nullable=True))

def downgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.drop_column("events")
