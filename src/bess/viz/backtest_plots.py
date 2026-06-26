"""Reproducible plots for the worked example exported to ``docs/figures/``.

Two figures, both built from objects the backtest already returns (no new math):

- :func:`plot_dispatch_day` — one representative day: price, net grid power
  (discharge up / charge down), and the SoC trajectory it produces;
- :func:`plot_baselines` — the three revenue quantities (greedy floor, rolling
  deployable, perfect-foresight ceiling) with the headline % of perfect foresight.

``matplotlib`` is an optional dependency (the ``examples`` group); importing this
module without it raises a clear ``ImportError``. ``viz`` sits outside the serving
chain and is not part of any import-linter contract.
"""

from __future__ import annotations

from bess.assets.battery import BatterySpec
from bess.backtest.engine import BacktestReport
from bess.optimizer.core import Schedule

try:
    import matplotlib

    matplotlib.use("Agg")  # headless: write files, never open a window
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "bess.viz needs matplotlib — install the examples extra: `uv sync --group examples`"
    ) from exc


def plot_dispatch_day(
    prices_day: list[float],
    schedule_day: Schedule,
    spec: BatterySpec,
    dt: float = 1.0,
    *,
    title: str = "Optimal dispatch — one day",
) -> Figure:
    """One day of dispatch: price (line) over net grid power (bars) + SoC (line).

    ``schedule_day`` must be the slice of the schedule covering exactly these
    ``prices_day`` periods (the example passes one calendar day).
    """
    n = len(prices_day)
    hours = list(range(n))
    net = [d - c for c, d in zip(schedule_day.p_charge, schedule_day.p_discharge, strict=True)]

    fig, ax_power = plt.subplots(figsize=(9, 4.5))

    colors = ["#2a9d8f" if v >= 0 else "#e76f51" for v in net]  # discharge / charge
    ax_power.bar(hours, net, width=0.8, color=colors, alpha=0.85, label="net power (MW)")
    ax_power.axhline(0, color="#888", linewidth=0.8)
    ax_power.set_xlabel("hour of day (UTC)")
    ax_power.set_ylabel("net grid power — discharge ↑ / charge ↓ (MW)")
    ax_power.set_xticks(hours[::2])

    ax_soc = ax_power.twinx()
    ax_soc.plot(
        hours, schedule_day.soc, color="#264653", linewidth=1.6, marker="o",
        markersize=3, label="SoC (MWh)",
    )  # fmt: skip
    ax_soc.set_ylabel("SoC (MWh)", color="#264653")
    ax_soc.set_ylim(0, spec.capacity * 1.05)

    ax_price = ax_power.twinx()
    ax_price.spines["right"].set_position(("axes", 1.12))
    ax_price.plot(hours, prices_day, color="#e9c46a", linewidth=2.0, label="price (€/MWh)")
    ax_price.set_ylabel("day-ahead price (€/MWh)", color="#b8860b")

    ax_power.set_title(title)
    fig.tight_layout()
    return fig


def plot_baselines(report: BacktestReport, *, title: str = "Backtest baselines") -> Figure:
    """Bar chart of the three revenue quantities + the headline % of perfect foresight."""
    names = ["greedy\nfloor", "rolling\ndeployable", "perfect-foresight\nceiling"]
    values = [
        report.greedy.revenue_eur,
        report.rolling.revenue_eur,
        report.perfect_foresight.revenue_eur,
    ]
    colors = ["#e76f51", "#2a9d8f", "#264653"]

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    bars = ax.bar(names, values, color=colors, alpha=0.9)
    ax.set_ylabel("revenue over horizon (€)")
    ax.set_title(title)
    for bar, v in zip(bars, values, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2, v, f"€{v:,.0f}",
            ha="center", va="bottom", fontsize=9,
        )  # fmt: skip

    # Headline as a footnote, not an in-plot annotation: keeps the bars unobscured.
    pct = report.pct_of_perfect_foresight
    ax.margins(y=0.12)  # headroom so the value labels clear the axes frame
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.text(
        0.5,
        0.02,
        f"Rolling (no look-ahead) captures {pct:.1%} of the perfect-foresight ceiling.",
        ha="center",
        fontsize=9,
        color="#555",
    )
    return fig
