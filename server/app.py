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
import re
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import history  # noqa: E402
from server.export_python import python_script  # noqa: E402
from server.simulate import SimError, build  # noqa: E402

# ---- Backend version (the thing that matters for washout: the recirc/MLSS fix) ----
# Keep this in sync with `src/lib/version.ts#APP_VERSION` — the UI shows both so a user
# can tell "I have the latest frontend" from "I have the latest backend".
API_VERSION = "0.8.0"
API_FEATURES = [
    "recirc-wired",          # clarifier + RAS + WAS loop (perfect-clarifier topology)
    "srt-control",           # every retention loop runs at a sludge age; WAS sized for it
    "effluent-from-clarifier",  # the reported effluent is the clarified stream, not the last reactor
    "dag-topology",          # parallel streets + side streams, not a single chain
    "self-retaining-units",  # SBR/MBR/MBBR/MABR/trickling filter keep their own solids
    "sbr-cycles",            # fill/react/settle/decant clock drives the aeration, with stagger
    "flow-bypass-control",   # a COD/N-steered branch around a stage
    "primary-clarifier",     # settlers with no return (primary / intermediate clarifier)
    "natural-draft-ventilation",  # trickling filters are aerobic by default
    "plant-controllers",     # controllers set kLa or pumps, measuring in any tank
    "run-history",           # every run is kept; list, reopen, compare, restore
    "ph-estimate",           # pH from alkalinity + dissolved CO2, measurable by controllers
    "feed-control",          # a controller can switch an influent on and off (with hold)
    "python-export",         # the diagram as a standalone script for another machine
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
    project: dict[str, Any] | None = Field(
        default=None, description="The whole diagram (nodes incl. text, edges, viewport), "
        "kept in the history so the run can be restored")
    label: str | None = Field(default=None, max_length=120,
                              description="Optional name for the run in the history")


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


def _remember(req: SimulateRequest, result: dict[str, Any] | None, error: str | None,
              elapsed: float) -> str | None:
    """Save the run to the history; a full disk must not cost the user their result."""
    try:
        return history.save_run(
            project=req.project or {"version": 1, "nodes": req.units, "edges": req.edges},
            request={"time_days": req.time_days, "influent_flow": req.influent_flow,
                     "influent_overrides": req.influent_overrides},
            result=result, error=error, elapsed_s=elapsed, label=req.label or "",
        )
    except Exception:  # pragma: no cover - defensive
        log.exception("could not save the run to the history")
        return None


@app.post("/api/simulate")
async def simulate(req: SimulateRequest) -> JSONResponse:
    # IMPORTANT: keep this `async def` and call the (blocking) solver directly. Uvicorn runs
    # sync `def` endpoints in a worker *thread*, and the peepypoo/Julia (PythonCall) engine
    # deadlocks outside the main thread. An async endpoint stays on the event loop (main
    # thread), where the engine works. The event loop is blocked for the duration of the
    # solve (~30–120 s), which is fine for this single-user tool.
    t0 = time.monotonic()
    try:
        result = build(
            req.units, req.edges,
            time_days=req.time_days,
            influent_overrides=req.influent_overrides or None,
            influent_flow=req.influent_flow,
        )
    except SimError as e:
        run_id = _remember(req, None, str(e), time.monotonic() - t0)
        return JSONResponse(status_code=422, content={"detail": str(e), "history_id": run_id})
    except Exception as e:  # pragma: no cover - defensive
        log.exception("simulate failed")
        run_id = _remember(req, None, f"Simulation failed: {e!r}", time.monotonic() - t0)
        return JSONResponse(status_code=500, content={"detail": f"Simulation failed: {e!r}",
                                                      "history_id": run_id})
    result["history_id"] = _remember(req, result, None, time.monotonic() - t0)
    return JSONResponse(result)


# ---- Export: the diagram as a Python script that runs on another machine --------------

@app.post("/api/export/python")
def export_python(req: SimulateRequest) -> Response:
    """A standalone script that simulates this diagram with this server's model adapter."""
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", (req.label or "plant").strip()).strip("_") or "plant"
    script = python_script(
        req.units, req.edges,
        time_days=req.time_days,
        influent_flow=req.influent_flow,
        influent_overrides=req.influent_overrides,
        app_version=API_VERSION,
        name=name,
    )
    return Response(content=script, media_type="text/x-python; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.py"'})


# ---- History: every run the server solved -------------------------------------------

class LabelRequest(BaseModel):
    label: str = Field(default="", max_length=120)


@app.get("/api/history")
def history_list() -> dict[str, Any]:
    return {"runs": history.list_runs(), "max_runs": history.MAX_RUNS}


@app.get("/api/history/{run_id}")
def history_get(run_id: str) -> JSONResponse:
    try:
        return JSONResponse(history.get_run(run_id))
    except history.HistoryError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})


@app.patch("/api/history/{run_id}")
def history_label(run_id: str, req: LabelRequest) -> JSONResponse:
    try:
        return JSONResponse(history.set_label(run_id, req.label))
    except history.HistoryError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})


@app.delete("/api/history/{run_id}")
def history_delete(run_id: str) -> JSONResponse:
    try:
        history.delete_run(run_id)
    except history.HistoryError as e:
        return JSONResponse(status_code=404, content={"detail": str(e)})
    return JSONResponse({"ok": True})


_DIST = Path(__file__).resolve().parent.parent / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
else:
    @app.get("/")
    def _no_dist() -> dict[str, str]:
        return {"message": "Frontend bundle missing. Run `npm run build` or use `npm run dev`."}
