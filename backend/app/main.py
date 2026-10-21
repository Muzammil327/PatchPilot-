import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, commands, health, prompt, repos, runs
from app.api.auth import require_session
from app.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("patchpilot")

app = FastAPI(title="PatchPilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    # The GitHub session travels as a cookie, so the browser must send credentials.
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def request_logging(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request id=%s method=%s path=%s status=%d duration_ms=%d",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


signed_in = [Depends(require_session)]

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(prompt.router, dependencies=signed_in)
app.include_router(repos.router, dependencies=signed_in)
app.include_router(runs.router, dependencies=signed_in)
app.include_router(commands.router, dependencies=signed_in)
