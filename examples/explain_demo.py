#!/usr/bin/env python3
"""Shadow-price explainability demo (R2.4) — the water value and the no-trade band.

Solves one designed day and prints, per period, *why* the battery charged, discharged,
or sat idle: the water value (the SoC-balance dual, the marginal worth of stored
energy) and the no-trade band it implies. The day is built to show the teaching case:
at t5 the battery **idles through a €175 spike**, holding its charge for the €200 peak
one hour later, because its water value (158) is higher than selling at 175 would earn.

The figure is **synthetic by design**, like the ingestion-guard and scenario-reduction
figures: it demonstrates a mechanism (the dual and its band), not a market result, so a
constructed instance is clearer than a real day and no price data is committed. Run:

    uv sync --group examples
    uv run python examples/explain_demo.py

Outputs ``docs/figures/example-water-value.svg``.
"""

from __future__ import annotations

from pathlib import Path

from bess.assets.battery import BatterySpec
from bess.explain.duals import explain_schedule
from bess.viz.explain_plots import plot_water_value

FIGURES = Path(__file__).resolve().parent.parent / "docs" / "figures"

# A designed day: two arbitrage cycles, and a hold-through-a-spike at t5. eta<1 gives
# the no-trade band a visible width (round-trip loss, not the price, makes it).
PRICES = [35.0, 14.0, 100.0, 45.0, 10.0, 175.0, 200.0, 60.0, 22.0]
BATTERY = BatterySpec(
    capacity=1.0, eta_charge=0.9, eta_discharge=0.9, soc_initial=0.0, soc_terminal=0.0
)


def main() -> None:
    exp = explain_schedule(PRICES, BATTERY, dt=1.0)

    print(f"Dispatch objective: €{exp.schedule.objective:.2f}\n")
    print(f"  {'t':>2}  {'price':>7}  {'action':>9}  {'water μ':>8}  {'no-trade band':>16}  reason")
    for t, p in enumerate(exp.periods):
        band = (
            f"[{p.band_low_eur_mwh:6.1f}, {p.band_high_eur_mwh:6.1f}]"
            if p.band_low_eur_mwh is not None
            else f"{'(suppressed)':>16}"
        )
        print(
            f"  {t:>2}  {p.price_eur_mwh:>7.1f}  {p.action:>9}  "
            f"{p.water_value_eur_mwh:>8.1f}  {band}  {p.reason}"
        )

    print(
        "\nThe water value is flat while the battery has room and steps only where SoC "
        "hits a bound;\nat t5 the price (175) sits inside the band, so the battery holds "
        "for the 200 peak at t6."
    )

    fig = plot_water_value(
        [p.price_eur_mwh for p in exp.periods],
        [p.water_value_eur_mwh for p in exp.periods],
        [p.band_low_eur_mwh for p in exp.periods],
        [p.band_high_eur_mwh for p in exp.periods],
        [p.action for p in exp.periods],
    )
    FIGURES.mkdir(parents=True, exist_ok=True)
    out = FIGURES / "example-water-value.svg"
    fig.savefig(out, format="svg", bbox_inches="tight")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
