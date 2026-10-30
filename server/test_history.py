"""Tests for the run history store — pure Python, uses a temporary directory.

Run with:  server/.venv/bin/python server/test_history.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import history  # noqa: E402


def _result(nh4: float) -> dict:
    n = 20
    eff = {s: [0.0] * n for s in ["S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P",
                                  "S_NO", "S_ND", "X_ND", "S_O"]}
    eff["S_NH"] = [nh4] * n
    return {"t_days": list(range(n)), "series": {"eff": eff}, "t_end_days": 19,
            "reactors": [{"label": "Tank"}], "warnings": ["w"], "setup": {"controllers": []}}


def test_save_list_get_label_delete():
    project = {"version": 1, "nodes": [{"id": "a", "type": "unit"}], "edges": []}
    ok = history.save_run(project=project, request={"time_days": 19}, result=_result(1.5),
                          error=None, elapsed_s=3.21, label="first")
    bad = history.save_run(project=project, request={}, result=None, error="boom",
                           elapsed_s=0.4)
    runs = history.list_runs()
    assert [r["id"] for r in runs] == sorted([ok, bad], reverse=True)
    meta = next(r for r in runs if r["id"] == ok)
    assert meta["status"] == "ok" and meta["effluent"]["NH4"] == 1.5 and meta["units"] == 1
    assert next(r for r in runs if r["id"] == bad)["status"] == "failed"
    rec = history.get_run(ok)
    assert rec["project"] == project and rec["result"]["t_end_days"] == 19
    assert history.set_label(ok, "  renamed ")["label"] == "renamed"
    assert history.get_run(ok)["meta"]["label"] == "renamed"
    history.delete_run(bad)
    assert [r["id"] for r in history.list_runs()] == [ok]


def test_bad_ids_are_refused():
    for bad in ("../etc/passwd", "x", "20261022-161530-zzzz"):
        try:
            history.get_run(bad)
        except history.HistoryError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_only_the_newest_runs_are_kept():
    keep = history.MAX_RUNS
    history.MAX_RUNS = 3
    try:
        for _ in range(5):
            history.save_run(project=None, request={}, result=None, error="x", elapsed_s=0)
        assert len(history.list_runs()) == 3
    finally:
        history.MAX_RUNS = keep


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            history.HISTORY_DIR = Path(tmp)
            try:
                fn()
                print(f"ok   {name}")
            except Exception as e:
                failures += 1
                print(f"FAIL {name}: {e!r}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
