"""add local email and password credentials"""
from alembic import op
import sqlalchemy as sa

revision = "0002_local_credentials"
down_revision = "0001_persistent_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(500), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_local_credentials_user_id", "local_credentials", ["user_id"])
    op.create_index("ix_local_credentials_email", "local_credentials", ["email"])


def downgrade() -> None:
    op.drop_table("local_credentials")
