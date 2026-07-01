#!/usr/bin/env python3
"""Ingestion-guard demo (R1.5b) — a corrupt feed caught before it reaches the solver.

Treats a synthetic day-ahead series as the "fetch": one day is delivered with a
bit-identical €0.00 stuck block (a frozen feed). The guard classifies it, falls
back to the last-known-good day, and the dispatch then solves on the *trustworthy*
prices. The overall provenance composes the two breakers (ADR-0013): a solve that
is optimal on stale fallback data is reported **degraded**, not healthy.

Everything is **synthetic** (``bess.data.fixtures.synthetic_day_ahead``) — no real
or committed market data. Run:

    uv sync --group examples
    uv run python examples/ingestion_guard_demo.py

Outputs ``docs/figures/example-ingestion-guard.svg``.
"""

from __future__ import annotations

from pathlib import Path

from bess.assets.battery import BatterySpec
from bess.backtest.baselines import solve_window
from bess.data.fixtures import synthetic_day_ahead
from bess.data.ingestion_guard import FeedStatus, compose_provenance, guarded_fetch
from bess.viz.backtest_plots import plot_ingestion_guard

FIGURES = Path(__file__).resolve().parent.parent / "docs" / "figures"
FAULT_SLICE = (10, 19)  # a 9-hour bit-identical €0.00 block → longest run ≥ 8 h → stuck feed


def main() -> None:
    spec = BatterySpec()  # 1 MWh / 1 MW, η = 0.95
    dt = 1.0

    # Last-known-good: yesterday's clean day. The "fetch": today's day, but frozen.
    last_known_good = synthetic_day_ahead(days=1, seed=1)
    corrupted = synthetic_day_ahead(days=1, seed=2).copy()
    corrupted.iloc[FAULT_SLICE[0] : FAULT_SLICE[1]] = 0.0

    result = guarded_fetch(lambda: corrupted, last_known_good=last_known_good)
    assert result.status is FeedStatus.ANOMALY  # the frozen feed is caught, not passed through

    # What would have happened (dispatch on corrupt prices) vs. what the guard did.
    corrupted_sched, _ = solve_window(corrupted.astype(float).tolist(), spec, dt)
    fallback_sched, _ = solve_window(result.prices.astype(float).tolist(), spec, dt)
    provenance = compose_provenance(result.status, "optimal")

    print("Ingestion-guard demo — synthetic day-ahead, 1 MWh / 1 MW asset")
    print(f"  feed classification   {result.status.value} ({result.reason})")
    print(f"  degraded / fell back  {result.degraded}")
    print("  dispatched on         last-known-good (trustworthy), not the corrupt feed")
    print("  solver on fallback    optimal")
    print(f"  overall provenance    {provenance}")

    FIGURES.mkdir(parents=True, exist_ok=True)
    fig = plot_ingestion_guard(
        corrupted.astype(float).tolist(),
        result.prices.astype(float).tolist(),
        corrupted_sched,
        fallback_sched,
        dt,
        reason=result.reason or "",
        provenance=provenance,
        fault_slice=FAULT_SLICE,
    )
    fig.savefig(FIGURES / "example-ingestion-guard.svg", bbox_inches="tight")
    print(f"\nFigure written to {FIGURES}/example-ingestion-guard.svg")


if __name__ == "__main__":
    main()
