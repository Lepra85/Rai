"""FastAPI app entrypoint for the Rai domain service."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rai import __version__
from rai.api import op as op_api
from rai.api import resolve as resolve_api
from rai.api import webhook as webhook_api
from rai.errors import RaiError

app = FastAPI(title="Rai Domain Service", version=__version__)
app.include_router(resolve_api.router)
app.include_router(op_api.router)
app.include_router(webhook_api.router)


@app.exception_handler(RaiError)
async def rai_error_handler(_request: Request, exc: RaiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": exc.code, "message": exc.message},
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
