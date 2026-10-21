"""Phase 0 foundation revision.

Feature tables are intentionally deferred to the shared-core and owner migrations.
"""

from typing import Sequence, Union


revision: str = "0001_foundation"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
