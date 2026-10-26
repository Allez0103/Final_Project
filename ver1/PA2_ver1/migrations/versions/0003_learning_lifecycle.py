"""Shared learning cycles and atomic model-pair activation history."""
from alembic import op
from pa2.storage.database import LearningCycle, ModelActivation

revision = '0003_learning_lifecycle'
down_revision = '0002_generation_learning'
branch_labels = None
depends_on = None


def upgrade():
    for model in (LearningCycle, ModelActivation):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in (ModelActivation, LearningCycle):
        model.__table__.drop(op.get_bind(), checkfirst=True)
