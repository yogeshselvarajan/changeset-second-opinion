"""auth columns: invite expiry and use counts, session token and CSRF hashes

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17

Additive only. Existing rows keep NULL in the new nullable columns; `use_count` defaults to 0.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("invite_codes") as batch:
        batch.add_column(sa.Column("code_id", sa.Text(), nullable=True))
        batch.add_column(sa.Column("max_uses", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("use_count", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("expires_at", _ts(), nullable=True))
    op.create_index("ix_invite_codes_code_id", "invite_codes", ["code_id"], unique=True)

    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("token_hash", sa.Text(), nullable=True))
        batch.add_column(sa.Column("csrf_hash", sa.Text(), nullable=True))
        batch.add_column(sa.Column("last_seen_at", _ts(), nullable=True))
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("last_seen_at")
        batch.drop_column("csrf_hash")
        batch.drop_column("token_hash")

    op.drop_index("ix_invite_codes_code_id", table_name="invite_codes")
    with op.batch_alter_table("invite_codes") as batch:
        batch.drop_column("expires_at")
        batch.drop_column("use_count")
        batch.drop_column("max_uses")
        batch.drop_column("code_id")
