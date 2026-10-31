"""email action tokens and session invalidation"""
from alembic import op
import sqlalchemy as sa

revision = "0003_email_actions"
down_revision = "0002_local_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "email_action_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_email_action_tokens_user_id", "email_action_tokens", ["user_id"])
    op.create_index("ix_email_action_tokens_purpose", "email_action_tokens", ["purpose"])


def downgrade() -> None:
    op.drop_table("email_action_tokens")
    op.drop_column("users", "session_version")
