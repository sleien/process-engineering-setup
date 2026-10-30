"""Simulation history — every run the server solves, kept on disk.

Each run is two files in ``server/history/``:

* ``<id>.meta.json`` — small: when, label, outcome, horizon, solve time and the effluent
  summary the history list shows. Listing reads only these.
* ``<id>.run.json.gz`` — the full record: the diagram that was simulated, the request
  options, and the result (or the error). Opening a run reads this.

Ids are ``YYYYMMDD-HHMMSS-xxxx``, so sorting them sorts by time. The newest
``MAX_RUNS`` are kept; older ones are removed when a new run is saved.
"""

from __future__ import annotations

import gzip
import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

HISTORY_DIR = Path(__file__).resolve().parent / "history"
MAX_RUNS = 100
_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")

# The effluent figures shown per run, as means over the last tenth of the run (an SBR
# plant's effluent swings with the cycle; the last point alone would be arbitrary).
_COD = ["S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P"]
_SOLIDS = ["X_I", "X_S", "X_BH", "X_BA", "X_P"]


class HistoryError(Exception):
    """A run id that is malformed or not on disk."""


def _paths(run_id: str) -> tuple[Path, Path]:
    if not _ID_RE.match(run_id):
        raise HistoryError(f"not a run id: {run_id!r}")
    return HISTORY_DIR / f"{run_id}.meta.json", HISTORY_DIR / f"{run_id}.run.json.gz"


def _effluent_summary(result: dict[str, Any]) -> dict[str, float]:
    eff = (result.get("series") or {}).get("eff") or {}
    n = len(result.get("t_days") or [])
    if not eff or n == 0:
        return {}
    start = max(0, n - max(1, n // 10))

    def mean(state: str) -> float:
        vals = eff.get(state) or []
        window = vals[start:] or vals[-1:]
        return sum(window) / len(window) if window else 0.0

    m = {s: mean(s) for s in set(_COD) | {"S_NH", "S_NO", "S_ND", "X_ND", "S_O"}}
    tkn = m["S_NH"] + m["S_ND"] + m["X_ND"] + 0.086 * (m["X_BH"] + m["X_BA"]) + 0.06 * m["X_P"]
    return {
        "COD": round(sum(m[s] for s in _COD), 2),
        "NH4": round(m["S_NH"], 2),
        "NO3": round(m["S_NO"], 2),
        "TN": round(tkn + m["S_NO"], 2),
        "TSS": round(0.75 * sum(m[s] for s in _SOLIDS), 2),
        "O2": round(m["S_O"], 2),
    }


def save_run(
    *,
    project: dict[str, Any] | None,
    request: dict[str, Any],
    result: dict[str, Any] | None,
    error: str | None,
    elapsed_s: float,
    label: str = "",
) -> str:
    """Write one run to disk and return its id. The caller decides what a failure costs."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    run_id = f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    units = [n for n in (project or {}).get("nodes", []) if n.get("type") == "unit"]
    meta = {
        "id": run_id,
        "created": now.isoformat(timespec="seconds"),
        "label": label,
        "status": "ok" if result is not None else "failed",
        "elapsed_s": round(float(elapsed_s), 1),
        "t_end_days": (result or {}).get("t_end_days") or request.get("time_days"),
        "units": len(units),
        "reactors": [r.get("label") for r in (result or {}).get("reactors", [])],
        "warnings": len((result or {}).get("warnings", [])),
        "controllers": len(((result or {}).get("setup") or {}).get("controllers", [])),
        "error": (error or "")[:400],
        "effluent": _effluent_summary(result) if result is not None else {},
    }
    meta_path, run_path = _paths(run_id)
    with gzip.open(run_path, "wt", encoding="utf-8") as f:
        json.dump({"meta": meta, "project": project, "request": request,
                   "result": result, "error": error}, f, separators=(",", ":"))
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    _prune()
    return run_id


def _prune() -> None:
    metas = sorted(HISTORY_DIR.glob("*.meta.json"))
    for old in metas[:-MAX_RUNS] if len(metas) > MAX_RUNS else []:
        run_id = old.name[: -len(".meta.json")]
        for p in _paths(run_id):
            p.unlink(missing_ok=True)


def list_runs() -> list[dict[str, Any]]:
    """Every saved run's summary, newest first."""
    if not HISTORY_DIR.is_dir():
        return []
    out = []
    for p in sorted(HISTORY_DIR.glob("*.meta.json"), reverse=True):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue          # a half-written or damaged file is skipped, not fatal
    return out


def get_run(run_id: str) -> dict[str, Any]:
    _, run_path = _paths(run_id)
    if not run_path.is_file():
        raise HistoryError(f"no run {run_id}")
    with gzip.open(run_path, "rt", encoding="utf-8") as f:
        record = json.load(f)
    # The label lives in the meta file once renamed; the record carries the original.
    meta_path, _ = _paths(run_id)
    if meta_path.is_file():
        record["meta"] = json.loads(meta_path.read_text(encoding="utf-8"))
    return record


def set_label(run_id: str, label: str) -> dict[str, Any]:
    meta_path, _ = _paths(run_id)
    if not meta_path.is_file():
        raise HistoryError(f"no run {run_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["label"] = label.strip()[:120]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def delete_run(run_id: str) -> None:
    meta_path, run_path = _paths(run_id)
    if not meta_path.is_file() and not run_path.is_file():
        raise HistoryError(f"no run {run_id}")
    for p in (meta_path, run_path):
        p.unlink(missing_ok=True)
