"""Export local development OpenAPI for generated frontend types."""

import json
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.context.dev_app import app

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[3] / "frontend/src/features/context/generated/openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Successfully exported OpenAPI to {target}")
