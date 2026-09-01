#!/usr/bin/env python3
"""Quickstart: the whole stack in one command, no token and no optional dependencies.

Four things, in the order they matter:

1. **Dispatch.** The deterministic MILP schedules one day against a known price curve.
2. **Baselines.** A walk-forward backtest bounds that schedule between a greedy floor
   and the perfect-foresight ceiling, and reports what a no-look-ahead policy captures.
3. **Explanation.** The state-of-charge dual (the *water value*) and the no-trade band
   it induces say *why* the battery holds through a high price instead of selling.
4. **Data trust.** The ingestion guard catches a frozen feed and dispatches on the
   last-known-good series, reporting the result as degraded rather than silently optimal.

Everything runs on the committed synthetic series
(``bess.data.fixtures.synthetic_day_ahead``), so the numbers here are illustrative,
not a market result. The headline real-data figures come from
``examples/worked_example.py`` with an ENTSO-E token; see ``docs/studies/``.

Run (about ten seconds, base install only)::

    uv sync
    uv run python examples/quickstart.py
"""

from __future__ import annotations

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.backtest.baselines import solve_window
from bess.backtest.engine import run_backtest
from bess.data.fixtures import synthetic_day_ahead
from bess.data.ingestion_guard import FeedStatus, compose_provenance, guarded_fetch
from bess.explain.duals import explain_schedule

DAYS = 30
DT = 1.0

# 1 MWh / 1 MW, eta = 0.95, wear priced at 15 EUR per MWh of storage-side throughput.
SPEC = BatterySpec(degradation=DegradationSpec(cost_per_mwh=15.0))

# A designed day for the explanation: the battery idles through the 175 price at t5,
# holding its charge for the 200 peak at t6. eta < 1 gives the no-trade band width.
EXPLAIN_PRICES = [35.0, 14.0, 100.0, 45.0, 10.0, 175.0, 200.0, 60.0, 22.0]
EXPLAIN_SPEC = BatterySpec(eta_charge=0.9, eta_discharge=0.9)

FROZEN_EUR_MWH = 73.07  # an arbitrary cent no market clears at for nine hours
FAULT_SLICE = (10, 19)


def rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def dispatch_one_day(prices: list[float], label: str) -> None:
    """Solve a single day and show the charge-low / discharge-high pattern."""
    rule(f"1. Dispatch: one day ({label}), prices known")
    schedule, _ = solve_window(prices, SPEC, DT)
    print(f"  net profit over the day: EUR {schedule.objective:,.2f} (net of wear)\n")

    lo, hi = min(prices), max(prices)
    print(f"  {'hour':>4}  {'price':>7}  {'action':>9}  {'SoC':>5}  price shape")
    for t, price in enumerate(prices):
        charge, discharge = schedule.p_charge[t], schedule.p_discharge[t]
        if charge > 1e-6:
            action = "charge"
        elif discharge > 1e-6:
            action = "discharge"
        else:
            action = "."
        soc = max(schedule.soc[t], 0.0)  # clamp the solver's -0.0 for display
        bar = "#" * (1 + int(28 * (price - lo) / (hi - lo)))
        print(f"  {t:>4}  {price:>7.2f}  {action:>9}  {soc:>5.2f}  {bar}")

    print("\n  A 1 MWh / 1 MW asset is a one-hour battery, so one full cycle per day is")
    print("  its physical ceiling. Wear at EUR 15 / MWh suppresses the shallow round")
    print("  trips whose spread would not clear it, which is why the rest is idle.")


def baselines(prices) -> None:
    """Bound the policy between a greedy floor and the perfect-foresight ceiling."""
    rule(f"2. Baselines: {DAYS} days, walk-forward")
    report = run_backtest(prices, SPEC, dt=DT, window="1D")
    print(f"  greedy floor (percentile rule)   EUR {report.greedy.revenue_eur:>9,.2f}")
    print(f"  rolling deployable (per-day)     EUR {report.rolling.revenue_eur:>9,.2f}")
    print(f"  perfect-foresight ceiling        EUR {report.perfect_foresight.revenue_eur:>9,.2f}")
    print(f"  rolling / ceiling                    {report.pct_of_perfect_foresight:>9.1%}")
    print(f"  every physical constraint holds      {report.constraint_satisfaction!s:>9}")
    print("\n  The ordering greedy <= rolling <= ceiling is a property-tested invariant,")
    print("  not an observation: a run that broke it would fail the gate.")


def explanation() -> None:
    """Print the water value and the no-trade band that explain each action."""
    rule("3. Explanation: why the battery holds")
    exp = explain_schedule(EXPLAIN_PRICES, EXPLAIN_SPEC, dt=DT)
    print(f"  {'hour':>4}  {'price':>7}  {'action':>9}  {'water value':>11}  {'no-trade band':>16}")
    for t, p in enumerate(exp.periods):
        band = (
            f"[{p.band_low_eur_mwh:6.1f}, {p.band_high_eur_mwh:6.1f}]"
            if p.band_low_eur_mwh is not None
            else f"{'(suppressed)':>16}"
        )
        print(
            f"  {t:>4}  {p.price_eur_mwh:>7.1f}  {p.action:>9}  "
            f"{p.water_value_eur_mwh:>11.1f}  {band}"
        )
    print("\n  At hour 5 the price (175) sits inside the band, so the battery holds its")
    print("  charge for the 200 peak at hour 6. The band's width comes from round-trip")
    print("  loss and wear, not from the price.")


def data_trust() -> None:
    """Catch a frozen feed and dispatch on the last-known-good series instead."""
    rule("4. Data trust: a frozen feed is caught before the solver")
    last_known_good = synthetic_day_ahead(days=1, seed=1)
    corrupted = synthetic_day_ahead(days=1, seed=2).copy()
    corrupted.iloc[FAULT_SLICE[0] : FAULT_SLICE[1]] = FROZEN_EUR_MWH

    result = guarded_fetch(lambda: corrupted, last_known_good=last_known_good)
    naive, _ = solve_window(corrupted.astype(float).tolist(), SPEC, DT)
    guarded, _ = solve_window(result.prices.astype(float).tolist(), SPEC, DT)

    print(f"  feed classification              {result.status.value} ({result.reason})")
    print(f"  profit if the fault went unseen  EUR {naive.objective:>9,.2f}  (on prices that lie)")
    print(f"  profit on last-known-good        EUR {guarded.objective:>9,.2f}  (trustworthy)")
    print(f"  reported provenance              {compose_provenance(result.status, 'optimal')}")
    assert result.status is FeedStatus.ANOMALY
    print("\n  A stale-but-present price is more dangerous than an outage because it")
    print("  fails silently, so the guard reports degraded rather than optimal.")


def main() -> None:
    print("bess-dispatch-optimizer quickstart")
    print("1 MWh / 1 MW asset, eta = 0.95, wear at EUR 15 / MWh throughput.")
    print("Synthetic prices: illustrative, not a market result.")

    prices = synthetic_day_ahead(days=DAYS)

    # The widest-spread day: where the charge-low / discharge-high pattern is clearest.
    by_day = list(prices.groupby(prices.index.normalize()))
    day_label, day = max(by_day, key=lambda kv: kv[1].max() - kv[1].min())
    dispatch_one_day(day.astype(float).tolist(), f"{day_label.date()}, widest spread")
    baselines(prices)
    explanation()
    data_trust()

    print("\nReal-data results, the formulation, and the measured studies (nulls included):")
    print("  README.md, docs/results.md, docs/studies/")


if __name__ == "__main__":
    main()
