"""
Nexora API — main entry point.

WHAT IS FASTAPI?
  A Python web framework. You define functions, decorate them with @router.get/post,
  and FastAPI turns them into HTTP endpoints automatically.

WHAT IS UVICORN?
  The server that actually runs FastAPI. Think of it as the engine.

HOW TO RUN:
  cd backend
  source .venv/bin/activate
  uvicorn app.main:app --reload

  Then open: http://localhost:8000/docs  ← interactive API playground
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import app.agents.handlers  # noqa: F401 — register all agents on startup
from app.api.routes import (
    admin,
    auth,
    email,
    extract,
    health,
    inbound,
    inbound_addresses,
    integrations,
    pipeline,
    runs,
    sheets,
    template_versions,
    templates,
    upload,
    uploads,
    users,
    waitlist,
    workflows,
)
from app.config import settings
from app.logging_config import setup_logging
from app.middleware.request_context import RequestContextMiddleware
from app.persistence.templates.bootstrap import ensure_pipeline_templates_seeded
from app.rate_limit import limiter

setup_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.persistence import get_data_backend_name

    settings.require_persistent_backend(get_data_backend_name())

    ensure_pipeline_templates_seeded()
    if settings.orphan_reclaim_on_startup:
        from app.services.pipeline.orphan_reclaim import (
            reclaim_all_running,
            reclaim_stale_running,
        )

        try:
            # With Redis workers, API restart must not fail in-flight worker jobs.
            if settings.job_queue_enabled:
                await reclaim_stale_running()
            else:
                await reclaim_all_running()
        except Exception:
            import logging

            logging.getLogger("runner").exception(
                "Orphan run reclaim on startup failed"
            )
    yield


app = FastAPI(
    title="Nexora API",
    description="Upload documents, describe a task, AI builds and runs a pipeline.",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes — each router file owns a group of endpoints
app.include_router(health.router)
app.include_router(integrations.router)
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(waitlist.router)
app.include_router(users.router)
app.include_router(upload.router)
app.include_router(uploads.router)
app.include_router(extract.router)
app.include_router(pipeline.router)
app.include_router(runs.router)
app.include_router(email.router)
app.include_router(sheets.router)
app.include_router(inbound.router)
app.include_router(inbound_addresses.router)
app.include_router(template_versions.router)
app.include_router(templates.router)
app.include_router(workflows.router)
