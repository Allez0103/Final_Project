"""Append-only generations, comparisons and automatic preference observations."""
from alembic import op
from pa2.storage.database import GenerationRecord, ConfirmationAnalysis, LearningObservation

revision = '0002_generation_learning'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    for model in (GenerationRecord, ConfirmationAnalysis, LearningObservation):
        model.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    for model in (LearningObservation, ConfirmationAnalysis, GenerationRecord):
        model.__table__.drop(op.get_bind(), checkfirst=True)
