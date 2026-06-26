"""Golden oracles for the walk-forward backtest — exact greedy / rolling / ceiling.

Contract: docs/specs/R1.4a-backtest.md § "Golden oracles".
Math: docs/formulation.md § "R1.4 — Backtest semantics (derived; no new model)".

Toy Sequence[float] inputs (no fixture); each window is `window` periods. The
three quantities and the provable ordering V_greedy <= V_roll <= V* are pinned.
"""

import pytest

from bess.assets.battery import BatterySpec
from bess.backtest.engine import run_backtest

TOL = 1e-6


def test_oracle_1_greedy_trades_at_a_loss():
    """1 day [40,42], eta=0.95. The 5% spread is below the ~10.8% round-trip
    breakeven: greedy follows the percentile rule and LOSES money; the MILP idles."""
    spec = BatterySpec(eta_charge=0.95, eta_discharge=0.95)
    rep = run_backtest([40.0, 42.0], spec, dt=1.0, window=2)

    assert rep.greedy.revenue_eur == pytest.approx(-2.095, abs=TOL)
    assert rep.rolling.revenue_eur == pytest.approx(0.0, abs=TOL)
    assert rep.perfect_foresight.revenue_eur == pytest.approx(0.0, abs=TOL)
    # V* == 0 => pct defined as 0.
    assert rep.pct_of_perfect_foresight == pytest.approx(0.0, abs=TOL)


def test_oracle_2_overnight_value_is_the_ceiling_gap():
    """2 days [10,40 | 50,5], eta=1. Ceiling carries SoC overnight (buy@10 d1,
    sell@50 d2 = 40); rolling commits per-day (30); gap 10 = overnight arbitrage."""
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0)
    rep = run_backtest([10.0, 40.0, 50.0, 5.0], spec, dt=1.0, window=2)

    assert rep.greedy.revenue_eur == pytest.approx(30.0, abs=TOL)
    assert rep.rolling.revenue_eur == pytest.approx(30.0, abs=TOL)
    assert rep.perfect_foresight.revenue_eur == pytest.approx(40.0, abs=TOL)
    assert rep.pct_of_perfect_foresight == pytest.approx(0.75, abs=TOL)
    assert rep.uplift_vs_greedy_eur == pytest.approx(0.0, abs=TOL)


def test_oracle_3_flat_prices_all_idle():
    """No spread => greedy, rolling, ceiling all idle at 0; degenerate pct -> 0."""
    spec = BatterySpec(eta_charge=1.0, eta_discharge=1.0)
    rep = run_backtest([20.0, 20.0, 20.0, 20.0], spec, dt=1.0, window=2)

    assert rep.greedy.revenue_eur == pytest.approx(0.0, abs=TOL)
    assert rep.rolling.revenue_eur == pytest.approx(0.0, abs=TOL)
    assert rep.perfect_foresight.revenue_eur == pytest.approx(0.0, abs=TOL)
    assert rep.pct_of_perfect_foresight == pytest.approx(0.0, abs=TOL)
