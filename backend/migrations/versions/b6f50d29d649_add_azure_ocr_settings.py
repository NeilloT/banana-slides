"""add azure ocr settings

Revision ID: b6f50d29d649
Revises: 018_add_project_title
Create Date: 2026-05-10 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b6f50d29d649'
down_revision = '018_add_project_title'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ocr_provider', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('azure_document_intelligence_endpoint', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('azure_document_intelligence_key', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('settings', schema=None) as batch_op:
        batch_op.drop_column('azure_document_intelligence_key')
        batch_op.drop_column('azure_document_intelligence_endpoint')
        batch_op.drop_column('ocr_provider')
