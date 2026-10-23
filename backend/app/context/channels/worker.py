"""CLI entrypoint for running P1 channel polling workers as a dedicated service."""

from __future__ import annotations

import logging
import signal
import sys
import time

from .manager import get_channel_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("p1.channels.worker")


def main() -> None:
    logger.info("Initializing P1 Real-Channel Inbound Workers...")
    manager = get_channel_manager()

    def handle_exit(signum: int, frame: Any) -> None:
        logger.info("Termination signal received (%s); shutting down channel workers...", signum)
        manager.stop_all_workers()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    manager.start_configured_workers()
    logger.info("Channel workers active. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        handle_exit(signal.SIGINT, None)


if __name__ == "__main__":
    main()
