"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tables are created by SQLAlchemy metadata.create_all in seed for MVP.
    # Keep this revision as a marker for future incremental migrations.
    pass


def downgrade() -> None:
    pass
