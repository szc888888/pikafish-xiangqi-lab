"""create persistent user, game, review and lifecycle tables"""
from alembic import op
import sqlalchemy as sa

revision = "0001_persistent_data"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    required = {"users", "user_identities", "privacy_consents", "games", "game_moves", "reviews", "review_items", "data_requests", "deletion_tombstones"}
    # The first deployment used SQLAlchemy create_all before Alembic was added.
    # Adopt that already-created schema when all tables are present; a partial
    # schema is rejected so it cannot be silently treated as migrated.
    if existing & required:
        if required <= existing:
            return
        raise RuntimeError(f"partial persistent schema exists: {sorted(existing & required)}")
    op.create_table("users", sa.Column("id", sa.String(36), primary_key=True), sa.Column("display_name", sa.String(120)), sa.Column("avatar_url", sa.String(500)), sa.Column("status", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_users_status", "users", ["status"])
    op.create_table("user_identities", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("issuer", sa.String(500), nullable=False), sa.Column("subject", sa.String(255), nullable=False), sa.Column("email", sa.String(320)), sa.Column("email_verified", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("issuer", "subject", name="uq_identity_issuer_subject"))
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    op.create_table("privacy_consents", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("policy_type", sa.String(32), nullable=False), sa.Column("policy_version", sa.String(64), nullable=False), sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False), sa.Column("withdrawn_at", sa.DateTime(timezone=True)))
    op.create_index("ix_privacy_consents_user_id", "privacy_consents", ["user_id"])
    op.create_table("games", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(120)), sa.Column("initial_fen", sa.String(220), nullable=False), sa.Column("current_fen", sa.String(220), nullable=False), sa.Column("red_to_move", sa.Boolean(), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_games_user_id", "games", ["user_id"])
    op.create_index("ix_games_status", "games", ["status"])
    op.create_table("game_moves", sa.Column("id", sa.String(36), primary_key=True), sa.Column("game_id", sa.String(36), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False), sa.Column("ply", sa.Integer(), nullable=False), sa.Column("side", sa.String(8), nullable=False), sa.Column("uci", sa.String(8), nullable=False), sa.Column("notation_zh", sa.String(32), nullable=False), sa.Column("before_fen", sa.String(220), nullable=False), sa.Column("after_fen", sa.String(220), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("game_id", "ply", name="uq_game_move_ply"))
    op.create_index("ix_game_moves_game_id", "game_moves", ["game_id"])
    op.create_table("reviews", sa.Column("id", sa.String(36), primary_key=True), sa.Column("game_id", sa.String(36), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("game_version", sa.Integer(), nullable=False), sa.Column("initial_fen_snapshot", sa.String(220), nullable=False), sa.Column("moves_snapshot", sa.JSON(), nullable=False), sa.Column("history_hash", sa.String(128), nullable=False), sa.Column("engine_name", sa.String(120)), sa.Column("engine_version", sa.String(120)), sa.Column("nnue_version", sa.String(120)), sa.Column("parameters", sa.JSON(), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("summary", sa.Text()), sa.Column("error_code", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_reviews_game_id", "reviews", ["game_id"])
    op.create_index("ix_reviews_user_id", "reviews", ["user_id"])
    op.create_table("review_items", sa.Column("id", sa.String(36), primary_key=True), sa.Column("review_id", sa.String(36), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False), sa.Column("ply", sa.Integer(), nullable=False), sa.Column("side", sa.String(8), nullable=False), sa.Column("move", sa.String(8), nullable=False), sa.Column("best_move", sa.String(8)), sa.Column("before_score", sa.JSON()), sa.Column("after_score", sa.JSON()), sa.Column("loss_cp", sa.Integer()), sa.Column("mate_value", sa.Integer()), sa.Column("grade", sa.String(24), nullable=False), sa.Column("pv", sa.JSON(), nullable=False), sa.Column("rule_stop_kind", sa.String(32)), sa.Column("rule_stop_message", sa.Text()), sa.UniqueConstraint("review_id", "ply", name="uq_review_item_ply"))
    op.create_index("ix_review_items_review_id", "review_items", ["review_id"])
    op.create_table("data_requests", sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("type", sa.String(16), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)), sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("artifact_key", sa.String(500)), sa.Column("error_code", sa.String(64)))
    op.create_index("ix_data_requests_user_id", "data_requests", ["user_id"])
    op.create_table("deletion_tombstones", sa.Column("user_id", sa.String(36), primary_key=True), sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False), sa.Column("purge_completed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for table in ("deletion_tombstones", "data_requests", "review_items", "reviews", "game_moves", "games", "privacy_consents", "user_identities", "users"):
        op.drop_table(table)
