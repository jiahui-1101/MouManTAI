"""Reproducible HTTP + real subprocess restart smoke using isolated PostgreSQL.

Run from backend with P1_TEST_DATABASE_URL set. Creates synthetic rows in the
test database only; never deletes data or touches the running development server.
"""

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from uuid import uuid4

import httpx
from sqlalchemy.engine import make_url

from .dev_database import create_p1_engine, initialize_p1_schema


@contextmanager
def running_backend(url: str, port: int):
    environment = os.environ | {"P1_DATABASE_URL": url, "P1_DEV_TENANT_ID": "synthetic_smoke_tenant"}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.context.dev_app:app", "--host", "127.0.0.1", "--port", str(port)],
                               env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            deadline = time.monotonic() + 20
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Smoke backend exited before startup")
                try:
                    if client.get("/dev/p1/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("Smoke backend startup timeout")
                time.sleep(0.1)
            yield client, process.pid
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    url = os.environ.get("P1_TEST_DATABASE_URL")
    if not url or not (make_url(url).database or "").endswith("_test"):
        raise SystemExit("Set an isolated P1_TEST_DATABASE_URL ending in _test; no database substitution is allowed")
    engine = create_p1_engine(url)
    initialize_p1_schema(engine)
    engine.dispose()
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    provider_id = f"p1-01-smoke-{uuid4().hex}"
    payload = dict(tenant_id="synthetic_smoke_tenant", channel="WHATSAPP", provider_message_id=provider_id,
                   sender_identity_id="synthetic_smoke_sender", sender_alias="Synthetic restart test",
                   received_at="2026-10-21T10:01:00+08:00", message_at="2026-10-21T10:00:00+08:00",
                   business_timezone="Asia/Kuala_Lumpur", text="  Synthetic request: 100 burgers tomorrow.\nPreserve original spacing.  ",
                   attachments=[], adapter_mode="SYNTHETIC")
    with running_backend(url, port) as (client, first_pid):
        created = client.post("/v1/messages/ingest", json=payload)
        assert created.status_code == 201, "First delivery must create a message"
        first = created.json()["message"]
        message_id = first["message_id"]
        assert client.get("/v1/messages", params={"search": provider_id}).json()["total"] == 1
        assert client.get(f"/v1/messages/{message_id}").json() == first
    # The first OS process is terminated and waited for before a new process starts.
    with running_backend(url, port) as (client, second_pid):
        assert first_pid != second_pid
        assert client.get(f"/v1/messages/{message_id}").json() == first
        duplicate = client.post("/v1/messages/ingest", json=payload | {"received_at": "2026-10-21T12:00:00+08:00"})
        assert duplicate.status_code == 200
        assert duplicate.json() == {"message": first, "duplicate": True}
        assert client.get("/v1/messages", params={"search": provider_id}).json()["total"] == 1
        conflict = client.post("/v1/messages/ingest", json=payload | {"text": "Conflicting retry"})
        assert conflict.status_code == 409
        assert client.get(f"/v1/messages/{message_id}").json()["raw"]["text"] == payload["text"]
    print(json.dumps(dict(result="PASS", database="isolated PostgreSQL _test", message_id=message_id,
                          first_backend_pid=first_pid, restarted_backend_pid=second_pid,
                          create_status=201, duplicate_status=200, conflict_status=409, logical_record_count=1,
                          processing_status=first["processing_status"])))


if __name__ == "__main__":
    main()
