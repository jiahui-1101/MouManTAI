"""Replaceable local entry point. Never deploy as the shared application."""

from fastapi import FastAPI

app = FastAPI(title="PromiseFlow P1 development only", version="0.0.1")


@app.get("/dev/p1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "synthetic-development"}
