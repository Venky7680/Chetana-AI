from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .core.config import get_settings
from .core.holmes_client import HolmesClient
from .core.precedents import CorpusStore
from .core.store import Store
from .gateway import Gateway
from .routers import (
    alerts,
    auth,
    evidence,
    governance,
    health,
    precedents,
    incidents,
    investigations,
    overview,
    platform,
    workflows,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.gateway = Gateway(settings)

    app.state.store = Store(settings.database_url)
    await app.state.store.create_all()

    app.state.holmes = HolmesClient(
        base_url=settings.holmes_base_url,
        api_key=settings.holmes_api_key,
        model=settings.holmes_model,
        chat_path=settings.holmes_chat_path,
        timeout_seconds=settings.holmes_timeout_seconds,
    )
    # Investigations run as background tasks; asyncio holds only a weak
    # reference, so the set here is what keeps them alive.
    app.state.investigation_tasks = set()

    # Per-client corpora, with the bundled file as a shared fallback for
    # tenants that have uploaded nothing. The fallback announces its own
    # provenance, so a demo corpus never passes for a client's own history.
    app.state.corpora = CorpusStore(
        settings.precedent_corpus_dir, fallback=settings.precedent_corpus_path
    )

    log = logging.getLogger("chetana")
    log.info(
        "started with %d tenant(s), global autonomy ceiling R%d",
        len(app.state.gateway.all_tenants()),
        settings.global_max_autonomy_tier,
    )
    log.info(
        "investigation engine: %s",
        f"{settings.holmes_base_url} ({settings.holmes_model})"
        if settings.holmes_base_url
        else "not configured",
    )
    tenants = app.state.gateway.all_tenants()
    with_corpus = sum(1 for t in tenants if app.state.corpora.corpus(t.id))
    log.info(
        "precedent corpora: %d of %d client(s) have their own; shared fallback %s",
        with_corpus,
        len(tenants),
        "loaded" if app.state.corpora.index("__none__") else "absent",
    )
    try:
        yield
    finally:
        for task in list(app.state.investigation_tasks):
            task.cancel()
        await app.state.holmes.aclose()
        await app.state.store.aclose()
        await app.state.gateway.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Backend-for-frontend for the Chetana AI console. Keep is the system "
            "of record for alerts, correlation and workflows; this service is the "
            "only thing that talks to it, through an explicit operation allowlist "
            "and a reversibility-based autonomy gate."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        response = await call_next(request)
        response.headers["x-chetana-version"] = "0.1.0"
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(health.router)
    for module in (
        auth,
        governance,
        overview,
        alerts,
        incidents,
        workflows,
        platform,
        investigations,
        evidence,
        precedents,
    ):
        app.include_router(module.router, prefix=API_PREFIX)

    return app


app = create_app()
