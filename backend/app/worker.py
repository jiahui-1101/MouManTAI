"""Outbox dispatcher worker entrypoint for MouManTAI."""

from __future__ import annotations

from app.core.outbox import run_worker
from app.db.session import SessionLocal


def main() -> None:
    run_worker(SessionLocal, poll_interval=1.0)


if __name__ == "__main__":
    main()
