"""Reproducible plots for the worked example exported to ``docs/figures/``.

Figures built from objects the pipeline already returns (no new math):

- :func:`plot_dispatch_day` — one representative day: price, net grid power
  (discharge up / charge down), and the SoC trajectory it produces;
- :func:`plot_ingestion_guard` — the reliability hero (R1.4c): a corrupt feed the
  guard rejected, beside the trustworthy last-known-good it dispatched on instead.

The baseline comparison (greedy floor / rolling deployable / perfect-foresight
ceiling) is reported as numbers in the README, not plotted: rolling is each day's
independent optimum, so its gap to the ceiling is pure cross-day carry — a single
figure adds nothing the table does not.

``matplotlib`` is an optional dependency (the ``examples`` group); importing this
module without it raises a clear ``ImportError``. ``viz`` sits outside the serving
chain and is not part of any import-linter contract.
"""

from __future__ import annotations

from bess.assets.battery import BatterySpec
from bess.optimizer.core import Schedule

try:
    import matplotlib

    matplotlib.use("Agg")  # headless: write files, never open a window
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.offsetbox import AnchoredOffsetbox, TextArea, VPacker
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "bess.viz needs matplotlib — install the examples extra: `uv sync --group examples`"
    ) from exc


# Colour contract — two roles kept strictly separate.
#
#   Directional (diverging): the sign of net grid power. Reserved for discharge vs
#   charge and used NOWHERE else, so the reader's "green = discharge" mapping never
#   leaks into a chart where it would be meaningless.
_DISCHARGE = "#2a9d8f"  # net power ≥ 0 — delivering to the grid
_CHARGE = "#e76f51"  # net power < 0 — drawing from the grid
#
#   Non-directional series carry no flow meaning, so they draw from a separate
#   (blue) family — validated steps from the data-viz reference palette.
_PRICE = "#e9c46a"  # day-ahead price line (its own hue, shared across figures)
_SOC = "#2a78d6"  # state-of-charge trajectory — a state, not a flow direction
# The three revenue baselines are an ordinal ladder (floor → deployable → ceiling),
# so one blue hue light→dark reads them as rungs toward the ceiling, not as rivals.
_BASELINE_RAMP = ("#86b6ef", "#3987e5", "#184f95")
_METHOD = "#2a78d6"  # the advocated method (categorical, no flow meaning)
_BASELINE_MUTED = "#898781"  # a recessive comparison baseline
_FAULT = "#d03b3b"  # corrupt-region status red (distinct from the charge hue)

# Consistent legend style across every figure.
_LEGEND_KW = {"fontsize": 8, "framealpha": 0.9}


def _set_flow_ylabel(ax) -> None:
    """Label a net-power y-axis, encoding direction as the discharge/charge colours
    (a small ■ before each word) rather than ↑/↓ arrows — so the cue reads without a
    separate legend box. Multi-colour text is stacked as rotated offset boxes."""
    parts = [
        ("net grid power   ", "#333333"),
        ("■ discharge", _DISCHARGE),
        ("   ", "#333333"),
        ("■ charge", _CHARGE),
        ("   (MW)", "#333333"),
    ]
    boxes = [
        TextArea(
            t, textprops={"color": c, "rotation": 90, "ha": "left", "va": "bottom", "fontsize": 9}
        )
        for t, c in parts
    ]
    # Reversed: VPacker stacks the first child topmost, but rotated text reads
    # bottom-to-top, so the last part must sit at the top of the stack.
    ybox = VPacker(children=boxes[::-1], align="bottom", pad=0, sep=0)
    ax.set_ylabel("")
    ax.add_artist(
        AnchoredOffsetbox(
            loc="center left",
            child=ybox,
            pad=0,
            frameon=False,
            bbox_to_anchor=(-0.10, 0.5),
            bbox_transform=ax.transAxes,
            borderpad=0,
        )  # fmt: skip
    )


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

    colors = [_DISCHARGE if v >= 0 else _CHARGE for v in net]
    ax_power.bar(hours, net, width=0.8, color=colors, alpha=0.85)
    ax_power.axhline(0, color="#888", linewidth=0.8)
    ax_power.set_xlabel("hour of day (UTC)")
    _set_flow_ylabel(ax_power)
    ax_power.set_xticks(hours[::2])

    ax_soc = ax_power.twinx()
    ax_soc.plot(
        hours, schedule_day.soc, color=_SOC, linewidth=1.6, marker="o",
        markersize=3,
    )  # fmt: skip
    ax_soc.set_ylabel("SoC (MWh)", color=_SOC)
    # Pad below 0 so an empty battery (SoC = 0) sits visibly above the axis floor
    # rather than being hidden on it; headroom above full for the marker.
    ax_soc.set_ylim(-spec.capacity * 0.06, spec.capacity * 1.08)

    ax_price = ax_power.twinx()
    ax_price.spines["right"].set_position(("axes", 1.12))
    ax_price.plot(hours, prices_day, color=_PRICE, linewidth=2.0)
    ax_price.set_ylabel("day-ahead price (€/MWh)", color="#b8860b")

    ax_power.set_title(title)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.text(
        0.5, 0.02,
        "Linear degradation prices every MWh of throughput equally (€/MWh), so the battery "
        "cycles only when a price\nspread clears the round-trip wear cost; shallower spreads "
        "that pure arbitrage would take are left idle.",
        ha="center", va="bottom", fontsize=8.5, color="#555",
    )  # fmt: skip
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
        bar_colors = [_DISCHARGE if v >= 0 else _CHARGE for v in net]
        ax.bar(hours, net, width=0.8, color=bar_colors, alpha=0.85)
        ax.axhline(0, color="#888", linewidth=0.8)
        _set_flow_ylabel(ax)
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
        ax_top.axvspan(a - 0.5, b - 0.5, color=_FAULT, alpha=0.15)
        ymax = ax_top.get_ylim()[1]
        ax_top.text(
            (a + b) / 2 - 0.5, ymax * 0.82, "corrupt",
            ha="center", color="#b00020", fontsize=8,
        )  # fmt: skip

    _panel(
        ax_bot, fallback_prices, fallback_schedule, _PRICE,
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

    ax_d.plot(kept_counts, dist_forward, "-o", color=_METHOD, label="forward selection")
    if dist_kmeans is not None:
        ax_d.plot(kept_counts, dist_kmeans, "--s", color=_BASELINE_MUTED, label="k-means baseline")
    ax_d.set_xlabel("kept scenarios")
    ax_d.set_ylabel("Kantorovich distance to original")
    ax_d.set_title(f"Distance preserved (from {n_generate} generated)")
    ax_d.legend(**_LEGEND_KW)
    ax_d.grid(alpha=0.3)

    ax_t.plot(kept_counts, times_ms, "-o", color=_METHOD)
    ax_t.set_xlabel("kept scenarios")
    ax_t.set_ylabel("reduction time (ms)")
    ax_t.set_title("Cost of reduction")
    ax_t.grid(alpha=0.3)

    fig.suptitle(title, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig


def plot_duration_sweep(
    durations_h: list[float],
    pct_of_perfect_foresight: list[float],
    annualized_per_mwh: list[float],
    *,
    title: str = "Storage duration sweep — capture ratio and per-MWh value",
) -> Figure:
    """The ADR-0022 duration axis (no new math): run the backtest across storage
    durations and show the two effects a single-duration headline hides.

    Left: rolling / ceiling capture ratio vs duration — falls as duration rises,
    because cross-day carry (which a deterministic day-ahead agent cannot reach)
    grows with duration. Right: annualized perfect-foresight ceiling per
    MWh-installed vs duration — diminishing returns, each added hour arbitrages a
    flatter slice of the daily spread. Drawn rather than asserted (the trend holds
    for typical price shapes, not adversarially).
    """
    fig, (ax_pct, ax_val) = plt.subplots(1, 2, figsize=(11, 4.2))

    ax_pct.plot(durations_h, [100.0 * p for p in pct_of_perfect_foresight], "-o", color=_METHOD)
    ax_pct.set_xlabel("storage duration (h)")
    ax_pct.set_ylabel("% of perfect foresight captured")
    ax_pct.set_title("Capture ratio falls with duration")
    ax_pct.grid(alpha=0.3)

    ax_val.plot(durations_h, annualized_per_mwh, "-o", color=_METHOD)
    ax_val.set_xlabel("storage duration (h)")
    ax_val.set_ylabel("annualized ceiling (€/MWh-installed·yr)")
    ax_val.set_title("Per-MWh value: diminishing returns")
    ax_val.grid(alpha=0.3)

    fig.suptitle(title, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig
