"""Create the initial application schema, including query indexes.

Revision ID: 20261009_0001
Revises:
"""
from alembic import op

from app.db.database import Base
from app.models import FeatureMeasurement, UploadedFile  # noqa: F401

revision = "20261009_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial baseline migration. Metadata includes indexes and constraints.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
