"""RQ worker entrypoint (runs inside the worker service)."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time

from redis import Redis
from rq import Queue, Worker

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("rino.worker")


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    logger.info("Starting Rino worker")

    conn = Redis.from_url(redis_url)
    for attempt in range(30):
        try:
            conn.ping()
            break
        except Exception:
            logger.info("Waiting for Redis... (%s/30)", attempt + 1)
            time.sleep(1)
    else:
        logger.error("Redis unavailable; exiting")
        sys.exit(1)

    # Import job module so RQ can resolve callables.
    import app.jobs.sandbox_run  # noqa: F401

    queues = [Queue("default", connection=conn)]
    worker = Worker(queues, connection=conn)

    def _stop(*_args: object) -> None:
        logger.info("Shutting down worker")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("Worker ready (queue=default)")
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
