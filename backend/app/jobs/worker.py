"""Arq worker — pull run_id jobs from Redis and execute the pipeline.

Start (Railway worker service)::

    arq app.jobs.worker.WorkerSettings
"""

from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger("jobs.worker")


async def execute_run_job(ctx: dict, run_id: str) -> None:
    """Arq job entrypoint — same ``execute_run`` the API used via BackgroundTasks."""
    from app.services.pipeline.runner import execute_run

    logger.info("Worker picked up run_id=%s", run_id)
    await execute_run(run_id)
    logger.info("Worker finished run_id=%s", run_id)


class WorkerSettings:
    """Settings consumed by ``arq app.jobs.worker.WorkerSettings``."""

    functions = [execute_run_job]
    # Long OCR + LLM runs; allow up to 30 minutes per job.
    job_timeout = 1800
    max_jobs = 1
    # Evaluated at import — REDIS_URL must be set in the worker process env.
    redis_settings = (
        RedisSettings.from_dsn(settings.redis_url.strip())
        if settings.redis_url.strip()
        else RedisSettings()
    )
