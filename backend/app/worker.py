"""Minimal long-running worker entrypoint for the Phase 0 compose stack.

Feature-specific outbox consumers belong to their owning modules and are intentionally
not implemented in Phase 0.
"""

from __future__ import annotations

import time


def main() -> None:
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
