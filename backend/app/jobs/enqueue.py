"""Schedule pipeline runs on Redis (Arq) or in-process when REDIS_URL is unset."""

from __future__ import annotations

import asyncio
import logging

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger("jobs")

_pool = None


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url.strip())


async def _get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings())
    return _pool


async def schedule_run(run_id: str) -> None:
    """Enqueue ``execute_run`` for ``run_id``, or run it in-process without Redis."""
    if not settings.job_queue_enabled:
        from app.services.pipeline.runner import execute_run

        logger.info("Job queue off — in-process execute_run run_id=%s", run_id)
        asyncio.create_task(execute_run(run_id))
        return

    pool = await _get_pool()
    job = await pool.enqueue_job("execute_run_job", run_id)
    logger.info(
        "Enqueued execute_run_job run_id=%s job_id=%s",
        run_id,
        getattr(job, "job_id", None),
    )
