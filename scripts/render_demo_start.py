"""Start a private Render service with an isolated managed PostgreSQL connection."""
import os
import signal
import socket
import subprocess
import sys
import time

from sqlalchemy.engine import make_url


def fail(message: str) -> None:
    raise SystemExit(f"Render Demo Admin start failed: {message}")


if len(sys.argv) != 2 or sys.argv[1] not in ("api", "worker", "migrate", "free"):
    fail("expected api, worker, migrate, or free")
mode = sys.argv[1]
service = os.getenv("RENDER_SERVICE_TYPE")
expected_service = "web" if mode == "free" else "worker" if mode == "worker" else "pserv"
if service != expected_service:
    fail("Render service type mismatch")
if mode == "free" and os.getenv("MOUMANTAI_DEMO_HOSTING") != "render-free":
    fail("free service requires colocated gateway mode")
raw = os.getenv("RENDER_DATABASE_URL", "")
try:
    url = make_url(raw)
except Exception:
    fail("invalid managed PostgreSQL URL")
if (url.drivername != "postgresql" or not url.host or
        url.host in ("localhost", "127.0.0.1", "db") or
        url.database != "moumantai_demo_staging" or not url.username or not url.password):
    fail("dedicated Render PostgreSQL required")
normalized = url.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = normalized
os.environ["P1_DATABASE_URL"] = normalized
os.environ["STAGING_DB_USER"] = url.username
subprocess.run([sys.executable, "/app/scripts/demo_admin_preflight.py"], check=True)

if mode in ("migrate", "free"):
    subprocess.run(["alembic", "-c", "alembic.ini", "upgrade", "head"], check=True)
    subprocess.run(["alembic", "-c", "alembic.ini", "current", "--check-heads"], check=True)
    if mode == "migrate":
        raise SystemExit(0)
if mode == "free":
    subprocess.run([sys.executable, "/app/scripts/seed_demo_free.py"], check=True)
    children = [
        subprocess.Popen(["uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]),
        subprocess.Popen([sys.executable, "-m", "app.worker"]),
    ]

    def stop(*_args: object) -> None:
        for child in children:
            if child.poll() is None:
                child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for _ in range(60):
        if any(child.poll() is not None for child in children):
            stop(); fail("private API or worker exited during startup")
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                break
        except OSError:
            time.sleep(1)
    else:
        stop(); fail("private API did not start")
    children.append(subprocess.Popen(["node", "/app/frontend/demoGateway.mjs"]))
    try:
        while all(child.poll() is None for child in children):
            time.sleep(1)
    finally:
        stop()
        for child in children:
            child.wait(timeout=10)
    fail("demo process exited; Render should restart the instance")
if mode == "worker":
    for _ in range(60):
        if subprocess.run(["alembic", "-c", "alembic.ini", "current", "--check-heads"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            break
        time.sleep(5)
    else:
        fail("database migrations did not complete")
command = (["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
           if mode == "api" else [sys.executable, "-m", "app.worker"])
os.execvp(command[0], command)
