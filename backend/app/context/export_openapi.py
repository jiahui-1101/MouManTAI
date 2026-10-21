"""Export local development OpenAPI for generated frontend types."""

import json
from pathlib import Path

from .dev_app import app

if __name__ == "__main__":
    target = Path(__file__).resolve().parents[3] / "frontend/src/features/context/generated/openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
