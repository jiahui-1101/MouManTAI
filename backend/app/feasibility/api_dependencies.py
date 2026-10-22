"""Override points for P5-approved P2 integration services.

Returning ``None`` means the integration has not been configured. Routers
translate that state to an explicit 503 rather than simulating persistence.
"""

import os
from secrets import compare_digest

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db
from app.core.errors import DomainError

from .ports import (
    AssessmentHistoryReader,
    AssessmentWriter,
    EvaluationInputAuthority,
    ImpactReader,
    SupplierDelayProcessor,
)


def get_internal_request_context() -> RequestContext | None:
    """P5 must override this with its approved internal caller boundary."""

    return None


def require_isolated_e2e_key(x_isolated_e2e_key: str | None = Header(default=None)) -> None:
    """Gate isolated mutation routes with a server-owned secret, not actor headers."""
    configured = os.getenv("MOUMANTAI_ISOLATED_E2E_KEY")
    if not configured or len(configured) < 32:
        raise DomainError("ISOLATED_E2E_NOT_CONFIGURED", "Isolated mutation key is unavailable", status_code=503)
    if x_isolated_e2e_key is None or not compare_digest(x_isolated_e2e_key, configured):
        raise DomainError("ISOLATED_E2E_UNAUTHORIZED", "Isolated mutation key is invalid", status_code=403)


def get_evaluation_input_authority(db: Session = Depends(get_db)) -> EvaluationInputAuthority | None:
    """Use persisted sources only in a controlled isolated integration process."""
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        return None
    from .persisted_sources import PersistedEvaluationAuthority

    return PersistedEvaluationAuthority(db)


def get_assessment_writer() -> AssessmentWriter | None:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        return None
    from app.core.feasibility_adapters import AuthoritativeAssessmentWriter

    return AuthoritativeAssessmentWriter()


def get_assessment_history() -> AssessmentHistoryReader | None:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        return None
    from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader

    return AuthoritativeAssessmentHistoryReader()


def get_supplier_delay_processor() -> SupplierDelayProcessor | None:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        return None
    from .persisted_sources import PersistedSupplierDelayProcessor

    return PersistedSupplierDelayProcessor()


def get_impact_reader() -> ImpactReader | None:
    if os.getenv("MOUMANTAI_ISOLATED_E2E") != "1":
        return None
    from .persisted_sources import PersistedImpactReader

    return PersistedImpactReader()
