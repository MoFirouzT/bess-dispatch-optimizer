"""Unit test for the duration sweep (ADR-0022 reporting).

Contract: docs/specs/R1.4a-backtest.md § "Duration as a reported axis".
The sweep is additive reporting over the existing engine; correctness at
``capacity != 1`` is already covered by tests/property/test_backtest.py. This
checks the sweep's shape and that each per-duration report is individually valid.

It deliberately does **not** assert a monotone capture-ratio-vs-duration trend:
that holds for typical daily price shapes but can break on adversarial series, so
asserting it would be a flaky, dishonest gate. The diminishing-returns trend is
shown in the example output, not gated here.
"""

from __future__ import annotations

from bess.assets.battery import BatterySpec
from bess.backtest.engine import DurationResult, run_duration_sweep
from bess.data.fixtures import synthetic_day_ahead

EPS_ORDER = 1e-4  # matches the cross-solve ordering tolerance in test_backtest.py


def test_duration_sweep_shape_and_validity() -> None:
    prices = synthetic_day_ahead(days=10, seed=1)
    base = BatterySpec()  # 1 MW / 1 MWh reference; power = 1 MW
    durations = (1.0, 2.0, 4.0)

    results = run_duration_sweep(prices, base, dt=1.0, durations=durations)

    assert [r.duration_h for r in results] == list(durations)
    for r, d in zip(results, durations, strict=True):
        assert isinstance(r, DurationResult)
        # power is held fixed; capacity scales with duration.
        assert r.capacity_mwh == base.p_discharge_max * d
        rep = r.report
        # each per-duration report satisfies the provable ordering + feasibility gate.
        assert rep.constraint_satisfaction
        assert rep.greedy.revenue_eur <= rep.rolling.revenue_eur + EPS_ORDER
        assert rep.rolling.revenue_eur <= rep.perfect_foresight.revenue_eur + EPS_ORDER
        assert 0.0 <= rep.pct_of_perfect_foresight <= 1.0 + EPS_ORDER


def test_duration_sweep_default_durations() -> None:
    prices = synthetic_day_ahead(days=5, seed=2)
    results = run_duration_sweep(prices, BatterySpec(), dt=1.0)
    assert [r.duration_h for r in results] == [1.0, 2.0, 4.0]
