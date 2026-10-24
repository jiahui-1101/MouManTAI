"""Opt-in synthetic reads. Header identity is a demo identity, never live auth."""
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.core.dependencies import ACTOR_ROLES, RequestContext, get_request_context
from app.core.errors import DomainError
from app.orders.demo_data import DemoDataset, load_demo_dataset


def demo_context(context: Annotated[RequestContext, Depends(get_request_context)]) -> RequestContext:
    if (os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
            or os.getenv("MOUMANTAI_ORDERS_DEMO") != "1"
            or os.getenv("MOUMANTAI_SYNTHETIC_MODE") != "1"):
        raise DomainError("ORDERS_DEMO_DISABLED", "Explicit non-production orders demo required", status_code=503)
    if (context.tenant_id != "tenant_demo_01" or context.actor_id not in ACTOR_ROLES
            or context.actor_role not in {"OWNER", "MANAGER", "STAFF"}):
        raise DomainError("FORBIDDEN", "Demo tenant and recognized human actor required", status_code=403)
    return context


Context = Annotated[RequestContext, Depends(demo_context)]
router = APIRouter(prefix="/v1/demo/orders", tags=["synthetic orders read-only"])


class DemoQueue(DemoDataset):
    actor_id: str
    read_authorized: Literal[True] = True


@router.get("", response_model=DemoQueue)
def queue(context: Context) -> DemoQueue:
    data = load_demo_dataset()
    return DemoQueue(**data.model_dump(), actor_id=context.actor_id)
