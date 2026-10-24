"""Local read-only demo launcher. Supply DPAPI credentials via process environment only."""
import os
from pathlib import Path
import sys

from sqlalchemy.engine import make_url


def validate_target(raw_url: str) -> None:
    target = make_url(raw_url)
    if (target.get_backend_name() != "postgresql" or target.host != "127.0.0.1"
            or target.port != 5434 or target.database != "moumantai_demo"):
        raise ValueError("Only 127.0.0.1:5434/moumantai_demo is permitted")


def main():
    raw_url = os.environ["DATABASE_URL"]
    secret = make_url(raw_url).password
    class RedactedStream:
        def __init__(self, stream):
            self.stream = stream
        def write(self, value):
            value = str(value).replace(raw_url, "[DEMO_DATABASE_URL]")
            return self.stream.write(value.replace(secret, "[REDACTED]") if secret else value)
        def flush(self):
            self.stream.flush()
        def isatty(self):
            return False
    sys.stdout = RedactedStream(sys.stdout)
    sys.stderr = RedactedStream(sys.stderr)
    validate_target(raw_url)
    if (os.environ.get("MOUMANTAI_ORDERS_DEMO") != "1" or
            os.environ.get("MOUMANTAI_SYNTHETIC_MODE") != "1" or
            os.environ.get("ENVIRONMENT", "").lower() in {"prod", "production"}):
        raise ValueError("Explicit non-production synthetic orders demo flags required")
    # Put connection options in BOTH URLs; URL options could otherwise override PGOPTIONS.
    target = make_url(raw_url).update_query_dict({"options": "-c default_transaction_read_only=on"})
    os.environ["DATABASE_URL"] = target.render_as_string(hide_password=False)
    os.environ["P1_DATABASE_URL"] = os.environ["DATABASE_URL"]
    os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on"
    os.environ["MOUMANTAI_ISOLATED_E2E"] = "0"
    os.environ["P4_TRUSTED_ISOLATED"] = "0"
    for name in ("TELEGRAM_AUTO_START", "GMAIL_AUTO_START", "P1_AI_ENABLED"):
        os.environ[name] = "false"
    for name in ("TELEGRAM_BOT_TOKEN", "GMAIL_CREDENTIALS_FILE", "GMAIL_CLIENT_ID",
                 "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "GMAIL_ACCESS_TOKEN",
                 "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_APP_SECRET",
                 "MOUMANTAI_ISOLATED_E2E_KEY", "P4_ISOLATED_PROCESSOR_KEY", "P4_ISOLATED_WORKER_KEY"):
        os.environ.pop(name, None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.db.session import engine
    from sqlalchemy import text
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar() == "moumantai_demo"
        assert connection.execute(text("SHOW default_transaction_read_only")).scalar() == "on"
    from app.main import app
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def read_only_http(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return JSONResponse(status_code=405, content={"code": "READ_ONLY_DEMO", "message": "Read-only demo runtime"})
        return await call_next(request)

    print("Orders SYNTHETIC read-only demo: 127.0.0.1:8001; database 5434/moumantai_demo", flush=True)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")


if __name__ == "__main__":
    main()
