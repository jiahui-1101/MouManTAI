import os
import sys
from pathlib import Path
import uvicorn

repo_root = Path(__file__).resolve().parents[1]
env_path = repo_root / ".env"

if env_path.is_file():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip("'\"")

os.environ.setdefault("MOUMANTAI_SYNTHETIC_MODE", "1")
os.environ.setdefault("P4_RUNTIME_MODE", "SYNTHETIC")
os.environ.setdefault("APP_ENV", "synthetic")
os.environ.setdefault("P4_SYNTHETIC_TENANTS", "synthetic_tenant_a,synthetic_tenant_b,tenant_demo_01")

# Ensure backend directory is in sys.path
backend_dir = repo_root / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
