"""Add metal_detected to scan_cycles.

Revision ID: 0002_add_metal_detected
Revises: 0001_initial
Create Date: 2026-09-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_add_metal_detected"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(existing["name"] == column for existing in inspector.get_columns(table))


def upgrade() -> None:
    # 0001_initial bootstraps the schema from the ORM metadata, so a database
    # created after this column was added to the models already has it; only
    # databases stamped at 0001 beforehand need the ALTER. Guard so both paths
    # converge on the same result. Existing rows predate the detector, so
    # backfill them to false.
    if not _has_column("scan_cycles", "metal_detected"):
        op.add_column(
            "scan_cycles",
            sa.Column(
                "metal_detected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    if _has_column("scan_cycles", "metal_detected"):
        op.drop_column("scan_cycles", "metal_detected")
