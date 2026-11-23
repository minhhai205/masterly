"""FastAPI application entry point.

Runtime settings live in ``data/user/settings/*.json`` and are created with
defaults on first start. Routers are mounted after the settings are in place,
because some of them read settings at import time.
"""

from contextlib import asynccontextmanager
import logging
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from masterly import __version__
from masterly.logging import configure_logging
from masterly.services.config import (
    ensure_runtime_settings_files,
    export_runtime_settings_to_env,
    load_system_settings,
)
from masterly.services.config.origins import normalize_origins
from masterly.services.path_service import get_path_service
from masterly.services.setup import ensure_agents_settings

ensure_runtime_settings_files()
ensure_agents_settings()
export_runtime_settings_to_env(overwrite=True)
configure_logging()
logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    """Allowed browser origins: the web app's own port plus any configured extras."""
    system_settings = load_system_settings()
    frontend_port = str(system_settings["frontend_port"])
    origins = [f"http://localhost:{frontend_port}", f"http://127.0.0.1:{frontend_port}"]
    for origin in normalize_origins([system_settings["cors_origin"], system_settings["cors_origins"]]):
        if origin not in origins:
            origins.append(origin)
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup")
    from masterly.services.auth import ensure_declared_admin

    ensure_declared_admin()
    get_path_service().get_workspace_dir().mkdir(parents=True, exist_ok=True)
    app.state.ready = True
    yield
    app.state.ready = False
    logger.info("Application shutdown")


app = FastAPI(
    title="Masterly API",
    version=__version__,
    lifespan=lifespan,
    # No automatic trailing-slash redirects: behind an HTTPS reverse proxy a 307
    # redirect could downgrade the scheme to HTTP.
    redirect_slashes=False,
)


@app.middleware("http")
async def json_error_boundary(request: Request, call_next):
    """Unhandled errors always come back as JSON with CORS headers.

    Registered as a middleware (not an exception handler) and before the CORS
    middleware, so the 500 response still travels out through CORS and the
    access log.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}", "type": type(exc).__name__},
        )


# Only non-200 responses are logged: routine polling would drown everything else.
_access_logger = logging.getLogger("masterly.access")
if not any(getattr(h, "_masterly_access_handler", False) for h in _access_logger.handlers):
    _access_handler = logging.StreamHandler(sys.stdout)
    _access_handler.setLevel(logging.INFO)
    _access_handler.setFormatter(logging.Formatter("%(message)s"))
    _access_handler._masterly_access_handler = True  # type: ignore[attr-defined]
    _access_logger.addHandler(_access_handler)
    _access_logger.setLevel(logging.INFO)
    _access_logger.propagate = False


@app.middleware("http")
async def selective_access_log(request: Request, call_next):
    response = await call_next(request)
    if response.status_code != 200:
        _access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            request.client.host if request.client else "-",
            request.method,
            request.url.path,
            request.scope.get("http_version", "1.1"),
            response.status_code,
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routers are imported only now: they read runtime settings at import time.
from fastapi import Depends  # noqa: E402

from masterly.api.routers import auth, model_settings, settings  # noqa: E402

# The auth router guards its own endpoints: status/login/logout are public.
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

# Everything else needs a session. The public UI-settings read is mounted first
# so the sign-in page can pick its theme and language before a session exists.
_auth = [Depends(auth.require_auth)]
app.include_router(settings.public_router, prefix="/api/settings", tags=["settings"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"], dependencies=_auth)
app.include_router(
    model_settings.router, prefix="/api/settings", tags=["settings"], dependencies=_auth
)


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready(request: Request):
    if not bool(getattr(request.app.state, "ready", False)):
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready", "version": __version__}
