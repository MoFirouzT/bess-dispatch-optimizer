"""Reproducible plots for the worked example exported to ``docs/figures/``.

Three figures, built from objects the pipeline already returns (no new math):

- :func:`plot_dispatch_day` — one representative day: price, net grid power
  (discharge up / charge down), and the SoC trajectory it produces;
- :func:`plot_baselines` — the three revenue quantities (greedy floor, rolling
  deployable, perfect-foresight ceiling) with the headline % of perfect foresight;
- :func:`plot_ingestion_guard` — the reliability hero (R1.4c): a corrupt feed the
  guard rejected, beside the trustworthy last-known-good it dispatched on instead.

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


def plot_ingestion_guard(
    corrupted_prices: list[float],
    fallback_prices: list[float],
    corrupted_schedule: Schedule,
    fallback_schedule: Schedule,
    dt: float = 1.0,
    *,
    reason: str,
    provenance: str,
    fault_slice: tuple[int, int] | None = None,
    title: str = "Ingestion guard — corrupt feed caught before dispatch",
) -> Figure:
    """Reliability hero (R1.4c): the corrupt feed the guard rejected, above the
    trustworthy last-known-good it dispatched on instead.

    Two stacked panels share the hour axis. Each shows net grid power (bars,
    discharge up / charge down) over the price curve (line). The top panel is the
    *rejected* feed (grey price, fault region shaded) — dispatching on it would run
    on corrupt prices; the bottom is the guard's fallback (amber price). The overall
    provenance caption makes the ADR-0013 composition explicit: a solve on stale
    data is degraded, not healthy.
    """
    hours = list(range(len(corrupted_prices)))

    fig, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(10, 7.5), sharex=True)

    def _panel(ax, prices: list[float], schedule: Schedule, price_color: str, subtitle: str):
        net = [d - c for c, d in zip(schedule.p_charge, schedule.p_discharge, strict=True)]
        bar_colors = ["#2a9d8f" if v >= 0 else "#e76f51" for v in net]  # discharge / charge
        ax.bar(hours, net, width=0.8, color=bar_colors, alpha=0.85)
        ax.axhline(0, color="#888", linewidth=0.8)
        ax.set_ylabel("net power\ndischarge ↑ / charge ↓ (MW)")
        ax.set_title(subtitle, loc="left", fontsize=10)
        ax_price = ax.twinx()
        ax_price.plot(hours, prices, color=price_color, linewidth=2.0)
        ax_price.set_ylabel("price (€/MWh)", color=price_color)
        return ax_price

    _panel(
        ax_top, corrupted_prices, corrupted_schedule, "#999999",
        f"① Feed delivered — REJECTED ({reason}): dispatch here would run on corrupt prices",
    )  # fmt: skip
    if fault_slice is not None:
        a, b = fault_slice
        ax_top.axvspan(a - 0.5, b - 0.5, color="#e76f51", alpha=0.15)
        ymax = ax_top.get_ylim()[1]
        ax_top.text(
            (a + b) / 2 - 0.5, ymax * 0.82, "corrupt",
            ha="center", color="#b00020", fontsize=8,
        )  # fmt: skip

    _panel(
        ax_bot, fallback_prices, fallback_schedule, "#e9c46a",
        "② Guard fell back to last-known-good: dispatch runs on trustworthy prices",
    )  # fmt: skip
    ax_bot.set_xlabel("hour of day (UTC)")
    ax_bot.set_xticks(hours[::2])

    fig.suptitle(title, fontsize=13, y=0.98)
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    fig.text(
        0.5, 0.015, f"overall provenance: {provenance}",
        ha="center", fontsize=10,
        color="#2a9d8f" if provenance == "healthy" else "#b00020",
    )  # fmt: skip
    return fig


def plot_scenario_reduction(
    kept_counts: list[int],
    dist_forward: list[float],
    times_ms: list[float],
    *,
    dist_kmeans: list[float] | None = None,
    n_generate: int,
    title: str = "Scenario reduction — count vs distance and cost",
) -> Figure:
    """The R2.2 trade-off (no new math): reduce a generated scenario set to varying
    sizes and show the two curves that motivate the method.

    Left: Kantorovich distance to the original vs kept count (forward selection,
    and the k-means baseline if supplied) — smaller kept sets lose more of the
    distribution. Right: reduction wall-clock vs kept count — the price paid.
    Together they are the "keep ~50 of 300" argument, drawn rather than asserted.
    """
    fig, (ax_d, ax_t) = plt.subplots(1, 2, figsize=(11, 4.2))

    ax_d.plot(kept_counts, dist_forward, "-o", color="#2a9d8f", label="forward selection")
    if dist_kmeans is not None:
        ax_d.plot(kept_counts, dist_kmeans, "--s", color="#e76f51", label="k-means baseline")
    ax_d.set_xlabel("kept scenarios")
    ax_d.set_ylabel("Kantorovich distance to original")
    ax_d.set_title(f"Distance preserved (from {n_generate} generated)")
    ax_d.legend()
    ax_d.grid(alpha=0.3)

    ax_t.plot(kept_counts, times_ms, "-o", color="#264653")
    ax_t.set_xlabel("kept scenarios")
    ax_t.set_ylabel("reduction time (ms)")
    ax_t.set_title("Cost of reduction")
    ax_t.grid(alpha=0.3)

    fig.suptitle(title, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig
