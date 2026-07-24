"""Smoke tests for the `examples/` scripts.

The README points readers at these scripts to reproduce every headline number and
figure, but nothing executed them: they are `__main__` scripts, not importable
package code, so the suite stayed green while one of them was broken. That is not
hypothetical. `ingestion_guard_demo` froze a 9 h **€0.00** block and asserted the
guard caught it; when the stuck-feed check moved from run *length* to the repeated
*value* (R1.4c), a zero run became legitimate market data and the script started
raising `AssertionError`, unnoticed.

Each script is executed with `main()`, so a crash anywhere fails the test. Two
things make that safe and fast:

- **`ENTSOE_API_TOKEN` is removed**, forcing the scripts' synthetic fallback. The
  smoke stays deterministic and never touches the network, even on a machine with a
  token in `.env`.
- **Figure output is redirected to `tmp_path`**, so running the suite can never
  rewrite a committed SVG. This matters: several scripts fall back to synthetic
  without a token, so an un-redirected run would silently replace a real-data figure
  with a synthetic one.

Expensive constants are shrunk to keep the suite fast; these assert the scripts
*run*, not that their numbers are right (the library gates own that).

matplotlib is an optional dependency (the `examples` group), absent in CI, so the
whole module skips there.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

# name -> (figure attribute to redirect, constants to shrink)
#   figure attr is None when the script writes no figure; note the three scripts that
#   do use three different names, and `scenario_reduction_demo`'s is a full file path
#   rather than a directory.
SCRIPTS: dict[str, tuple[str | None, dict]] = {
    "benchmark_scaling": (None, {"HORIZONS_H": [24], "STOCH_SCENARIOS": [4], "REPEATS": 1}),
    "ingestion_guard_demo": ("FIGURES", {}),
    "worked_example": ("FIGURES", {}),
    "duration_sweep": ("FIGURES", {"DURATIONS": (1.0, 2.0)}),
    "scenario_reduction_demo": ("FIG", {"N_GENERATE": 20, "KEPT_COUNTS": [5, 10]}),
    "spike_tail_demo": ("FIG", {"N_DAYS": 12, "N_SCENARIOS": 60}),
    "conditional_tail_demo": ("FIG", {"N_DAYS": 30}),
    "forecast_demo": ("FIG", {"N_ESTIMATORS": 25, "N_DAYS": 30}),
    "drift_demo": ("FIG", {"GRID_N": 12}),
    "explain_demo": ("FIGURES", {}),
    "stochastic_demo": (
        "FIG_DIR",
        {"N_SCENARIOS": 12, "LAMBDAS": [0.0, 0.5], "RHOS": [0.0, 0.3]},
    ),
    "vss_study": (
        "FIG_DIR",
        {
            "HISTORY_DAYS": 4,
            "N_SCENARIOS": 4,
            "N_SYNTH_DAYS": 7,
            "RUN_FORECAST_BASELINE": False,
        },
    ),
}


def _load(script: str):
    """Import an `examples/` script as a module (they are scripts, not a package)."""
    spec = importlib.util.spec_from_file_location(script, EXAMPLES / f"{script}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("script", sorted(SCRIPTS))
def test_example_script_runs(script: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fig_attr, consts = SCRIPTS[script]

    # forecast_demo needs the optional `forecast` group (LightGBM/MAPIE); skip where
    # matplotlib is present but that group is not.
    if script == "forecast_demo":
        pytest.importorskip("lightgbm")
        pytest.importorskip("mapie")

    # Force the token-free synthetic path: deterministic, no network, no quota.
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)

    mod = _load(script)

    if fig_attr is not None:
        target = tmp_path / "fig.svg" if fig_attr == "FIG" else tmp_path
        monkeypatch.setattr(mod, fig_attr, target)
    for key, value in consts.items():
        assert hasattr(mod, key), f"{script} no longer defines {key}; update SCRIPTS"
        monkeypatch.setattr(mod, key, value)

    mod.main()

    if fig_attr is not None:
        assert list(tmp_path.glob("*.svg")), f"{script} wrote no figure"


def test_guard_demo_still_injects_a_real_fault():
    """`ingestion_guard_demo` asserts its own premise (the injected fault must classify
    ANOMALY), which is what makes running it a genuine regression test for the guard.

    Pin the premise explicitly too: the frozen value must be **non-focal**. Freezing at
    €0.00 would inject legitimate market data rather than a fault, which is exactly how
    the script broke, and the assertion inside it would then fail for the right reason
    but only when someone happened to run it.
    """
    from bess.data.ingestion_guard import is_focal_price

    mod = _load("ingestion_guard_demo")
    lo, hi = mod.FAULT_SLICE
    assert hi - lo > 4, "fault must exceed the non-focal allowance (4 h at hourly)"
    assert not is_focal_price(mod.FROZEN_EUR_MWH), (
        f"demo freezes at {mod.FROZEN_EUR_MWH}, a focal price: that is legitimate "
        "market behaviour, not a stuck feed, so the demo would assert a false premise"
    )
