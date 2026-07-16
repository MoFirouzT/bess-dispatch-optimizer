"""Reproducible R2.1 / R2.1b figures exported to ``docs/figures/`` (no new math).

- :func:`plot_forecast_intervals` — a fan chart of the conformal price forecaster
  (R2.1) on a held-out block: the calibrated interval as a shaded band, the point
  forecast, and the realized price overlaid, so the reader can *see* that the
  realized price falls inside the band about ``confidence_level`` of the time.
- :func:`plot_drift_regions` — the drift monitor's (R2.1b) attribution map over
  (error-ratio × PSI): the classifier's decision regions rendered as a categorical
  field, with labelled example windows showing staleness vs. regime shift vs.
  miscalibration.

``matplotlib`` is an optional dependency (the ``examples`` group); importing this
module without it raises a clear ``ImportError``. ``viz`` sits outside the serving
chain and is not part of any import-linter contract. Following the house style, the
plots take raw sequences (not the forecaster's domain objects), so ``viz`` stays
decoupled from ``forecaster``.
"""

from __future__ import annotations

from collections.abc import Sequence

try:
    import matplotlib

    matplotlib.use("Agg")  # headless: write files, never open a window
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "bess.viz needs matplotlib — install the examples extra: `uv sync --group examples`"
    ) from exc


def plot_forecast_intervals(
    hours: Sequence[float],
    point: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
    realized: Sequence[float],
    *,
    confidence_level: float = 0.9,
    coverage: float | None = None,
    title: str = "Conformal price forecast — calibrated intervals",
) -> Figure:
    """Fan chart of a calibrated interval forecast against the realized price.

    ``hours`` indexes the held-out block; ``lower``/``upper`` are the conformal
    interval, ``point`` the median forecast, ``realized`` the price that actually
    cleared. ``coverage`` (the pooled walk-forward empirical coverage) is annotated
    when supplied — the honest test is that it lands near ``confidence_level``.
    """
    fig, ax = plt.subplots(figsize=(9.0, 4.6))

    pct = round(confidence_level * 100)
    ax.fill_between(
        hours, lower, upper, color="#2a9d8f", alpha=0.22, label=f"{pct}% interval", zorder=1
    )
    ax.plot(hours, point, "-", color="#264653", lw=1.6, label="point forecast", zorder=2)
    ax.plot(hours, realized, "o", color="#e76f51", markersize=3.5, label="realized price", zorder=3)

    ax.set_xlabel("hour of held-out block")
    ax.set_ylabel("day-ahead price (EUR/MWh)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", framealpha=0.9)

    if coverage is not None:
        ax.annotate(
            f"empirical coverage {coverage * 100:.1f}% (nominal {pct}%)",
            xy=(0.015, 0.03),
            xycoords="axes fraction",
            fontsize=9,
            color="#264653",
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#264653", alpha=0.85),
        )

    fig.tight_layout()
    return fig


def plot_drift_regions(
    ratios: Sequence[float],
    psis: Sequence[float],
    status_codes: Sequence[Sequence[int]],
    legend: Sequence[tuple[int, str, str]],
    *,
    points: Sequence[tuple[float, float, str]] | None = None,
    staleness_ratio: float = 1.3,
    psi_warn: float = 0.2,
    title: str = "Drift attribution — error ratio vs. input shift",
) -> Figure:
    """The drift monitor's decision regions over (error-ratio × PSI).

    ``status_codes[j][i]`` is the integer status the classifier returns at
    ``ratios[i]`` × ``psis[j]`` (computed by the caller with the real ``classify_drift``,
    so the regions are the code's, not drawn by hand). ``legend`` maps each code to a
    ``(code, label, color)`` triple. ``points`` are labelled example windows
    ``(ratio, psi, label)`` overlaid on the map; a miscalibration point sits inside the
    healthy region because coverage is an orthogonal third axis this map cannot show.
    """
    import numpy as np
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    codes = [code for code, _, _ in legend]
    cmap = ListedColormap([color for _, _, color in legend])
    norm = BoundaryNorm([c - 0.5 for c in codes] + [codes[-1] + 0.5], cmap.N)

    fig, ax = plt.subplots(figsize=(8.0, 5.2))
    # rasterized: the mesh is a dense field of cells; embedding it as a small raster
    # keeps the committed SVG light while the axes, lines, and labels stay vector.
    ax.pcolormesh(
        np.asarray(ratios), np.asarray(psis), np.asarray(status_codes),
        cmap=cmap, norm=norm, shading="auto", alpha=0.55, rasterized=True,
    )  # fmt: skip

    # The two threshold lines the classifier keys on (ADR-0015 precedence).
    ax.axvline(staleness_ratio, color="#264653", lw=1.2, ls="--", alpha=0.7)
    ax.axhline(psi_warn, color="#264653", lw=1.2, ls="--", alpha=0.7)

    if points is not None:
        for ratio, psi_value, label in points:
            ax.plot(ratio, psi_value, "o", color="#1d1d1d", markersize=6, zorder=4)
            ax.annotate(
                label,
                xy=(ratio, psi_value),
                xytext=(6, 6),
                textcoords="offset points",
                fontsize=9,
                color="#1d1d1d",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#1d1d1d", alpha=0.85),
            )

    ax.set_xlabel("error ratio  (forecaster MAE / seasonal-naive MAE)")
    ax.set_ylabel("input shift  (PSI of realized vs. reference)")
    ax.set_title(title)
    ax.legend(
        handles=[Patch(facecolor=color, alpha=0.55, label=label) for _, label, color in legend],
        loc="upper right",
        framealpha=0.9,
    )
    fig.tight_layout()
    return fig
