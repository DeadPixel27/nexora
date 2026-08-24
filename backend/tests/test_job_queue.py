"""Job queue scheduling — Redis enqueue vs in-process fallback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings


@pytest.mark.asyncio
async def test_schedule_run_in_process_when_no_redis(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "")
    assert settings.job_queue_enabled is False

    with patch(
        "app.services.pipeline.runner.execute_run",
        new_callable=AsyncMock,
    ) as execute:
        from app.jobs.enqueue import schedule_run

        await schedule_run("run-123")
        # create_task schedules; give the loop a tick
        import asyncio

        await asyncio.sleep(0)
        execute.assert_awaited_once_with("run-123")


@pytest.mark.asyncio
async def test_schedule_run_enqueues_when_redis_configured(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://localhost:6379")
    assert settings.job_queue_enabled is True

    fake_job = MagicMock()
    fake_job.job_id = "job-abc"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)

    with patch("app.jobs.enqueue._pool", None), patch(
        "app.jobs.enqueue.create_pool",
        new_callable=AsyncMock,
        return_value=fake_pool,
    ):
        # Reset module pool between tests
        import app.jobs.enqueue as enqueue_mod

        enqueue_mod._pool = None
        await enqueue_mod.schedule_run("run-456")

    fake_pool.enqueue_job.assert_awaited_once_with("execute_run_job", "run-456")
