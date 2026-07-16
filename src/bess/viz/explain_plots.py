"""Reproducible R2.4 figure exported to ``docs/figures/`` (no new math).

- :func:`plot_water_value` — the shadow-price explanation of one dispatch day: the
  water value (the SoC-balance dual) as a step line, the no-trade band it implies as
  a shaded ribbon, and the price marked by the action it triggered (charge below the
  band, discharge above, idle inside). The teaching case is a period that idles
  through a price spike because the water value is higher still.

``matplotlib`` is an optional dependency (the ``examples`` group); importing this
module without it raises a clear ``ImportError``. ``viz`` sits outside the serving
chain and is not part of any import-linter contract. Following the house style, the
plot takes raw sequences (read off an ``Explanation``), not the domain object.
"""

from __future__ import annotations

from collections.abc import Sequence

try:
    import matplotlib

    matplotlib.use("Agg")  # headless: write files, never open a window
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "bess.viz needs matplotlib — install the examples extra: `uv sync --group examples`"
    ) from exc

_CHARGE = "#e76f51"  # price drew energy in
_DISCHARGE = "#2a9d8f"  # price paid energy out
_IDLE = "#6c757d"  # neither: price inside the no-trade band
_WATER = "#2a78d6"  # water value (a stored-energy state, blue like SoC)
_BAND = "#2a78d6"  # the no-trade band ribbon (same hue, low alpha)
_PRICE = "#b8860b"  # day-ahead price line

_ACTION_COLOR = {"charge": _CHARGE, "discharge": _DISCHARGE, "idle": _IDLE}


def plot_water_value(
    prices: Sequence[float],
    water_value: Sequence[float],
    band_low: Sequence[float | None],
    band_high: Sequence[float | None],
    actions: Sequence[str],
    *,
    title: str = "Why the battery traded — water value and the no-trade band",
) -> Figure:
    """Explain a dispatch day through its SoC-balance dual.

    ``water_value`` is mu_t (EUR/MWh); ``band_low``/``band_high`` are the no-trade
    band edges, ``None`` where a run is unpinned (no band drawn there); ``actions`` is
    one of ``"charge"``/``"discharge"``/``"idle"`` per period. The band is a stepped
    ribbon (mu is flat within a run, so it steps only where SoC hits a bound); the
    price sits where the band explains it: below to charge, above to discharge, inside
    to idle. An idle point above the surrounding charge prices is the battery holding
    through a spike for a higher water value.
    """
    n = len(prices)
    hours = list(range(n))
    lo = np.array([np.nan if b is None else b for b in band_low], dtype=float)
    hi = np.array([np.nan if b is None else b for b in band_high], dtype=float)

    fig, ax = plt.subplots(figsize=(9.5, 5.0))

    # No-trade band: a stepped ribbon between the two edges (flat within each run).
    ax.fill_between(
        hours, lo, hi, step="mid", color=_BAND, alpha=0.15, label="no-trade band", zorder=1
    )
    # Water value: a step line (constant while SoC is interior, steps at a bound).
    ax.step(
        hours, list(water_value), where="mid", color=_WATER, lw=1.8, label="water value μ", zorder=2
    )
    # Price line, then each point marked by the action the band triggered.
    ax.plot(hours, list(prices), color=_PRICE, lw=1.4, alpha=0.7, zorder=3)
    for t in hours:
        ax.scatter(
            t,
            prices[t],
            color=_ACTION_COLOR[actions[t]],
            s=64,
            zorder=4,
            edgecolor="white",
            linewidth=0.8,
        )

    # Annotate the first idle period whose price rises above the previous one: the
    # battery holding through a spike rather than selling into it.
    hold = next(
        (t for t in range(1, n) if actions[t] == "idle" and prices[t] > prices[t - 1]), None
    )
    if hold is not None:
        span = max(prices) - min(prices)
        ax.annotate(
            "holds through the spike:\nwater value is higher",
            xy=(hold, prices[hold]),
            xytext=(hold - 2.4, prices[hold] - 0.30 * span),
            ha="left",
            fontsize=9,
            color=_IDLE,
            arrowprops={
                "arrowstyle": "->",
                "color": _IDLE,
                "lw": 1.2,
                "connectionstyle": "arc3,rad=-0.2",
            },
        )

    ax.set_xlabel("period (hour)")
    ax.set_ylabel("EUR/MWh")
    ax.set_title(title)
    ax.set_xticks(hours)
    ax.grid(True, alpha=0.25)

    handles = [
        Line2D([], [], color=_WATER, lw=1.8, label="water value μ"),
        plt.Rectangle((0, 0), 1, 1, color=_BAND, alpha=0.15, label="no-trade band"),
        Line2D([], [], color=_PRICE, lw=1.4, alpha=0.7, label="day-ahead price"),
        Line2D([], [], marker="o", color=_CHARGE, lw=0, label="charge", markersize=8),
        Line2D([], [], marker="o", color=_DISCHARGE, lw=0, label="discharge", markersize=8),
        Line2D([], [], marker="o", color=_IDLE, lw=0, label="idle", markersize=8),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=8.5, framealpha=0.9)

    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.text(
        0.5,
        0.015,
        "The water value is the marginal worth of stored energy (the SoC-balance dual). It is flat "
        "while the battery has room,\nand steps only where SoC hits a bound. The battery charges "
        "when the price is below the band, discharges above it, and idles inside.",
        ha="center",
        va="bottom",
        fontsize=8.5,
        color="#555",
    )
    return fig
