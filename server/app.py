"""FastAPI app: /api/simulate endpoint + static delivery of the built frontend.

Run from the repo root:

    server/.venv/bin/uvicorn server.app:app --port 8080

After `npm run build` has produced `dist/`, open http://localhost:8080 — one port, one
server, UI and simulation API in the same process.

During development, `npm run dev` (Vite on 5173) proxies `/api/*` to this server on 8080
(see `vite.config.ts`).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.simulate import SimError, build  # noqa: E402

# ---- Backend version (the thing that matters for washout: the recirc/MLSS fix) ----
# Keep this in sync with `src/lib/version.ts#APP_VERSION` — the UI shows both so a user
# can tell "I have the latest frontend" from "I have the latest backend".
API_VERSION = "0.2.0"
API_FEATURES = [
    "recirc-wired",          # clarifier + RAS + WAS loop (perfect-clarifier topology)
    "mlss-srt-control",      # periodic callback holds MLSS at the clarifier target
    "effluent-from-clarifier",  # the reported effluent is the clarified stream, not the last reactor
]

log = logging.getLogger("server")

app = FastAPI(title="WWTP Designer API", version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:8080", "http://127.0.0.1:8080"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SimulateRequest(BaseModel):
    units: list[dict[str, Any]] = Field(
        description="Unit nodes (type='unit') with data.unitId, data.attributes, data.name"
    )
    edges: list[dict[str, Any]] = Field(
        description="Pipe edges with data.streamType, data.flow, data.name"
    )
    time_days: float | None = Field(default=None, ge=0.5, le=90)
    influent_flow: float | None = Field(default=None, ge=1, le=1_000_000,
                                        description="Optional user-set influent flow in m³/d")
    influent_overrides: dict[str, float] = Field(default_factory=dict,
                                                 description="Optional per-state influent composition overrides (name → value)")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/version")
def version() -> dict[str, Any]:
    """Served version + which simulation features this backend builds.

    The UI shows this so a user can (a) confirm the app is the latest and (b) see whether
    the washout fix (recirculation + MLSS/SRT control) is present in the backend they're
    talking to — that's the backend that actually builds the model.
    """
    return {"version": API_VERSION, "features": API_FEATURES}


@app.post("/api/simulate")
async def simulate(req: SimulateRequest) -> JSONResponse:
    # IMPORTANT: keep this `async def` and call the (blocking) solver directly. Uvicorn runs
    # sync `def` endpoints in a worker *thread*, and the peepypoo/Julia (PythonCall) engine
    # deadlocks outside the main thread. An async endpoint stays on the event loop (main
    # thread), where the engine works. The event loop is blocked for the duration of the
    # solve (~30–120 s), which is fine for this single-user tool.
    try:
        return JSONResponse(build(
            req.units, req.edges,
            time_days=req.time_days,
            influent_overrides=req.influent_overrides or None,
            influent_flow=req.influent_flow,
        ))
    except SimError as e:
        return JSONResponse(status_code=422, content={"detail": str(e)})
    except Exception as e:  # pragma: no cover - defensive
        log.exception("simulate failed")
        return JSONResponse(status_code=500, content={"detail": f"Simulation failed: {e!r}"})


_DIST = Path(__file__).resolve().parent.parent / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
else:
    @app.get("/")
    def _no_dist() -> dict[str, str]:
        return {"message": "Frontend bundle missing. Run `npm run build` or use `npm run dev`."}
