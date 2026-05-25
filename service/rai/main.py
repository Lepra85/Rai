"""FastAPI app entrypoint for the Rai domain service."""
from __future__ import annotations

from fastapi import FastAPI

from rai import __version__

app = FastAPI(title="Rai Domain Service", version=__version__)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
