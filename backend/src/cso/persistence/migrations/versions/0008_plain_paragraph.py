"""plainer default community paragraph

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19

Data only. The first default wording used engineering terms ("cut points", "receipt names the
version"); the home page now says it in plain words. An admin's own wording is never touched: the
row is changed only while it still holds the old default, word for word.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "A community can pick a pack of settings, such as a more welcoming one for newcomers or a "
    "stricter one, and tune the cut points from its own reviewers' decisions. Nothing applies by "
    "itself, and every receipt names the version it ran with."
)
NEW = (
    "Every community looks after the map in its own way. Pick a pack that fits yours, such as a "
    "warmer welcome for newcomers or closer scrutiny, and adjust it from your own reviewers' "
    "decisions. Nothing changes unless an admin applies it."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE workspaces SET community_paragraph = :new WHERE community_paragraph = :old"
        ).bindparams(new=NEW, old=OLD)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE workspaces SET community_paragraph = :old WHERE community_paragraph = :new"
        ).bindparams(new=NEW, old=OLD)
    )
