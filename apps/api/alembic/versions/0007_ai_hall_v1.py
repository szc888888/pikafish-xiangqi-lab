"""persist AI hall metadata, formal results and idempotent turns"""

from alembic import op
import sqlalchemy as sa


revision = "0007_ai_hall_v1"
down_revision = "0006_game_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.add_column(sa.Column("mode", sa.String(24), nullable=False, server_default="legacy"))
        batch_op.add_column(sa.Column("user_side", sa.String(8), nullable=True))
        batch_op.add_column(sa.Column("opponent_id", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("opponent_config_version", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("opponent_snapshot", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("result", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("termination_reason", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("origin", sa.String(24), nullable=False, server_default="legacy"))
        batch_op.add_column(sa.Column("counts_for_stats", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index("ix_games_opponent_id", ["opponent_id"])
        batch_op.create_index("ix_games_user_mode_status_updated", ["user_id", "mode", "status", "updated_at"])

    op.create_table(
        "game_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("turn_id", sa.String(128), nullable=False),
        sa.Column("game_id", sa.String(36), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("user_uci", sa.String(8), nullable=True),
        sa.Column("user_ply", sa.Integer(), nullable=True),
        sa.Column("ai_uci", sa.String(8), nullable=True),
        sa.Column("ai_ply", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="ai_pending"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("game_id", "turn_id", name="uq_game_turn_id"),
    )
    op.create_index("ix_game_turns_game_id", "game_turns", ["game_id"])
    op.create_index("ix_game_turns_status", "game_turns", ["status"])


def downgrade() -> None:
    op.drop_index("ix_game_turns_status", table_name="game_turns")
    op.drop_index("ix_game_turns_game_id", table_name="game_turns")
    op.drop_table("game_turns")
    with op.batch_alter_table("games") as batch_op:
        batch_op.drop_index("ix_games_user_mode_status_updated")
        batch_op.drop_index("ix_games_opponent_id")
        batch_op.drop_column("counts_for_stats")
        batch_op.drop_column("origin")
        batch_op.drop_column("finished_at")
        batch_op.drop_column("termination_reason")
        batch_op.drop_column("result")
        batch_op.drop_column("opponent_snapshot")
        batch_op.drop_column("opponent_config_version")
        batch_op.drop_column("opponent_id")
        batch_op.drop_column("user_side")
        batch_op.drop_column("mode")
