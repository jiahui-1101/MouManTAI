"""Override points for P5-approved P2 integration services.

Returning ``None`` means the integration has not been configured. Routers
translate that state to an explicit 503 rather than simulating persistence.
"""

from app.core.dependencies import RequestContext

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


def get_evaluation_input_authority() -> EvaluationInputAuthority | None:
    """P5 must verify supplied snapshot/commitment data against trusted state."""

    return None


def get_assessment_writer() -> AssessmentWriter | None:
    return None


def get_assessment_history() -> AssessmentHistoryReader | None:
    return None


def get_supplier_delay_processor() -> SupplierDelayProcessor | None:
    return None


def get_impact_reader() -> ImpactReader | None:
    return None
