"""Align Recovery Case schema constraints and foreign key policies (P3 Handoff P3-1).

Revision ID: 0007_recovery_case_constraints_alignment
Revises: 0006_recovery_cases
Create Date: 2026-10-22

Aligns recovery_cases and recovery_case_triggers schema constraints with P3 ORM expectations:
1. Replaces unique constraint name `uq_recovery_case_tenant_case_commitment` (singular)
   with `uq_recovery_cases_tenant_case_commitment` (plural) on recovery_cases (tenant_id, case_id, commitment_id).
2. Modifies `fk_recovery_case_triggers_case_tenant_commitment` foreign key on recovery_case_triggers
   from ON DELETE CASCADE to ON DELETE RESTRICT, preserving append-only trigger history.
3. Preserves composite primary keys, partial unique active case index, and all existing table records.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0007_recovery_case_constraints_alignment"
down_revision: Union[str, None] = "0006_recovery_cases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # 1. Drop trigger-to-case FK from recovery_case_triggers
        op.drop_constraint(
            "fk_recovery_case_triggers_case_tenant_commitment",
            "recovery_case_triggers",
            type_="foreignkey",
        )
        # 2. Drop old singular unique constraint from recovery_cases
        op.drop_constraint(
            "uq_recovery_case_tenant_case_commitment",
            "recovery_cases",
            type_="unique",
        )
        # 3. Create new plural unique constraint on recovery_cases
        op.create_unique_constraint(
            "uq_recovery_cases_tenant_case_commitment",
            "recovery_cases",
            ["tenant_id", "case_id", "commitment_id"],
        )
        # 4. Re-create trigger-to-case FK with ON DELETE RESTRICT
        op.create_foreign_key(
            "fk_recovery_case_triggers_case_tenant_commitment",
            "recovery_case_triggers",
            "recovery_cases",
            ["tenant_id", "case_id", "commitment_id"],
            ["tenant_id", "case_id", "commitment_id"],
            ondelete="RESTRICT",
        )
    else:
        # SQLite / batch mode
        with op.batch_alter_table("recovery_case_triggers") as batch_op:
            batch_op.drop_constraint(
                "fk_recovery_case_triggers_case_tenant_commitment",
                type_="foreignkey",
            )
        with op.batch_alter_table("recovery_cases") as batch_op:
            batch_op.drop_constraint(
                "uq_recovery_case_tenant_case_commitment",
                type_="unique",
            )
            batch_op.create_unique_constraint(
                "uq_recovery_cases_tenant_case_commitment",
                ["tenant_id", "case_id", "commitment_id"],
            )
        with op.batch_alter_table("recovery_case_triggers") as batch_op:
            batch_op.create_foreign_key(
                "fk_recovery_case_triggers_case_tenant_commitment",
                "recovery_cases",
                ["tenant_id", "case_id", "commitment_id"],
                ["tenant_id", "case_id", "commitment_id"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # 1. Drop RESTRICT FK from recovery_case_triggers
        op.drop_constraint(
            "fk_recovery_case_triggers_case_tenant_commitment",
            "recovery_case_triggers",
            type_="foreignkey",
        )
        # 2. Drop plural unique constraint from recovery_cases
        op.drop_constraint(
            "uq_recovery_cases_tenant_case_commitment",
            "recovery_cases",
            type_="unique",
        )
        # 3. Re-create singular unique constraint on recovery_cases
        op.create_unique_constraint(
            "uq_recovery_case_tenant_case_commitment",
            "recovery_cases",
            ["tenant_id", "case_id", "commitment_id"],
        )
        # 4. Re-create trigger-to-case FK with ON DELETE CASCADE
        op.create_foreign_key(
            "fk_recovery_case_triggers_case_tenant_commitment",
            "recovery_case_triggers",
            "recovery_cases",
            ["tenant_id", "case_id", "commitment_id"],
            ["tenant_id", "case_id", "commitment_id"],
            ondelete="CASCADE",
        )
    else:
        # SQLite / batch mode
        with op.batch_alter_table("recovery_case_triggers") as batch_op:
            batch_op.drop_constraint(
                "fk_recovery_case_triggers_case_tenant_commitment",
                type_="foreignkey",
            )
        with op.batch_alter_table("recovery_cases") as batch_op:
            batch_op.drop_constraint(
                "uq_recovery_cases_tenant_case_commitment",
                type_="unique",
            )
            batch_op.create_unique_constraint(
                "uq_recovery_case_tenant_case_commitment",
                ["tenant_id", "case_id", "commitment_id"],
            )
        with op.batch_alter_table("recovery_case_triggers") as batch_op:
            batch_op.create_foreign_key(
                "fk_recovery_case_triggers_case_tenant_commitment",
                "recovery_cases",
                ["tenant_id", "case_id", "commitment_id"],
                ["tenant_id", "case_id", "commitment_id"],
                ondelete="CASCADE",
            )
