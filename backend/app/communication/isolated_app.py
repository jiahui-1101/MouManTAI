"""Explicit isolated server entrypoint with private P1 evidence surface.

P1's provisional inbox returns raw normalized text, including customer reply
codes. It must not be a public browser API in this composition. Production
authentication/identity remain a separate P1/P5 responsibility.
"""
from contextvars import ContextVar
import os
from secrets import compare_digest
from starlette.responses import JSONResponse

private_inbound_surface = ContextVar("p4_private_inbound_surface", default=False)


class PrivateInboundGateway:
    def __init__(self, application):
        self.application = application
        from app.context.router import router
        self.p1_paths = [route.path_regex for route in router.routes]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.application(scope, receive, send)
        if any(pattern.fullmatch(scope["path"]) for pattern in self.p1_paths):
            headers = {key.lower():value for key,value in scope.get("headers", [])}
            supplied = headers.get(b"x-p4-processor-key",b"")
            secret = os.getenv("P4_ISOLATED_PROCESSOR_KEY", "").encode()
            from .demo_policy import SyntheticScope
            policy = SyntheticScope.from_environment()
            tenant = headers.get(b"x-tenant-id", b"").decode("utf-8", errors="replace")
            if (len(secret)<32 or not compare_digest(secret,supplied) or
                headers.get(b"x-actor-id") != b"service_core" or not policy.enabled or tenant not in policy.tenants):
                return await JSONResponse({"code":"P1_PRIVATE_PROCESSOR_REQUIRED",
                    "message":"Raw P1 evidence is restricted to the authenticated processor"},status_code=403)(scope,receive,send)
        token = private_inbound_surface.set(True)
        try:
            return await self.application(scope, receive, send)
        finally:
            private_inbound_surface.reset(token)


def create_isolated_application():
    from .trusted_runtime import enabled
    if not enabled():
        raise RuntimeError("This entrypoint requires explicit P4_TRUSTED_ISOLATED=1")
    from app.main import app
    return PrivateInboundGateway(app)

# Run through uvicorn's factory option. Importing this module does not install
# a wrapper into the shared App or mutate another owner's routes.
# python -m uvicorn app.communication.isolated_app:create_isolated_application --factory
