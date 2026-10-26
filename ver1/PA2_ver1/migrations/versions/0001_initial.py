"""Baseline existing PA2 schema; checkfirst supports previously initialized DBs."""
from alembic import op
from pa2.storage.database import Base

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

NEW = {'plan_generations', 'confirmation_analyses', 'learning_observations', 'learning_cycles', 'model_activations'}


def upgrade():
    Base.metadata.create_all(op.get_bind(), tables=[t for t in Base.metadata.sorted_tables if t.name not in NEW])


def downgrade():
    Base.metadata.drop_all(op.get_bind(), tables=[t for t in Base.metadata.sorted_tables if t.name not in NEW])
