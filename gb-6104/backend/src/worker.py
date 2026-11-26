import logging
import time

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.config.resources import cache, engine
from src.services.execution import JobFailure, fail, recover_stale, service_one

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

# How often to look for batches whose worker died mid-computation.
RECOVERY_INTERVAL = 30


def check():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    heartbeat = cache.get("workbench:heartbeat")
    return heartbeat is not None and time.time() - float(heartbeat) < 90


def work():
    last_recovery = 0.0
    while True:
        try:
            cache.set("workbench:heartbeat", time.time(), ex=90)
            if time.monotonic() - last_recovery >= RECOVERY_INTERVAL:
                recover_stale()
                last_recovery = time.monotonic()
            try:
                if service_one():
                    continue
            except JobFailure as exc:
                logger.exception("Execution %s failed", exc.run_id)
                fail(exc)
                continue
            cache.blpop("workbench:wake", timeout=1)
        except (RedisError, SQLAlchemyError):
            logger.exception("Worker connection unavailable")
            time.sleep(2)


if __name__ == "__main__":
    work()
