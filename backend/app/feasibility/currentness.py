"""Current-version acceptance guard shared by the public route and benchmark.

This checks the provider's explicit token, not source authenticity or atomicity.
The production writer must still recheck it inside the write transaction.
"""

from app.core.errors import DomainError

from .production import EvaluationSnapshot


def require_current_snapshot(snapshot: EvaluationSnapshot, *, correlation_id: str | None = None) -> None:
    if snapshot.current_snapshot_version is None:
        raise DomainError('P2_CURRENT_SNAPSHOT_VERSION_UNAVAILABLE',
                          'P5 has not supplied current operational snapshot version authority',
                          status_code=503, correlation_id=correlation_id)
    if snapshot.current_snapshot_version != snapshot.operational.snapshot_version:
        raise DomainError('SNAPSHOT_VERSION_CONFLICT',
                          'Operational snapshot is not the current tenant snapshot', status_code=409,
                          details={'requested_snapshot_version': snapshot.operational.snapshot_version,
                                   'current_snapshot_version': snapshot.current_snapshot_version},
                          correlation_id=correlation_id)
