"""Reproducible R2.3/R2.5 figures exported to ``docs/figures/`` (no new math).

- :func:`plot_risk_return_frontier` — the mean-CVaR frontier: expected profit
  against downside (loss CVaR) as the risk weight λ sweeps 0 → 1;
- :func:`plot_vss_curve` — the value of the stochastic solution against the
  recourse budget ρ, showing VSS = 0 at both limits and a positive interior;
- :func:`plot_vss_distribution` — the R2.5 per-window out-of-sample VSS
  distribution: one bar-coded window per day plus the summary that carries the
  claim (median, share of windows above zero);
- :func:`plot_value_by_regime` — the R2.7 per-year view of that same
  distribution, with the block-bootstrap interval on each year's median, so a
  pooled figure cannot hide a finding that holds in one regime and not another.

``matplotlib`` is an optional dependency (the ``examples`` group); importing this
module without it raises a clear ``ImportError``. ``viz`` sits outside the serving
chain and is not part of any import-linter contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # a type-only import: viz must not pull `studies` in at runtime
    from bess.studies.summary import WindowSummary

try:
    import matplotlib

    matplotlib.use("Agg")  # headless: write files, never open a window
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "bess.viz needs matplotlib — install the examples extra: `uv sync --group examples`"
    ) from exc


def plot_risk_return_frontier(
    expected_profit: Sequence[float],
    cvar_loss: Sequence[float],
    lambdas: Sequence[float],
    *,
    title: str = "Risk-return frontier (mean-CVaR)",
) -> Figure:
    """Expected profit vs downside (loss CVaR) along the λ sweep.

    Each point is one risk weight λ; the endpoints are the risk-neutral solution
    (λ=0, top-right) and the most risk-averse (λ→1, bottom-left).
    """
    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    ax.plot(cvar_loss, expected_profit, "-", color="#264653", alpha=0.6, zorder=1)
    sc = ax.scatter(
        cvar_loss, expected_profit, c=lambdas, cmap="viridis", s=60, zorder=2, edgecolor="white"
    )
    fig.colorbar(sc, ax=ax, label="risk weight λ")

    ax.set_xlabel("downside — CVaR of loss (EUR, lower is safer)")
    ax.set_ylabel("expected profit (EUR)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_vss_curve(
    rhos: Sequence[float],
    vss: Sequence[float],
    *,
    title: str = "Value of the stochastic solution vs recourse budget",
) -> Figure:
    """VSS against the recourse fraction ρ; zero at both limits, positive between."""
    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    ax.plot(rhos, vss, "-o", color="#2a9d8f", markersize=5)
    ax.axhline(0.0, color="#e76f51", lw=1, ls="--", alpha=0.7)

    ax.set_xlabel("recourse budget ρ (fraction of rated power)")
    ax.set_ylabel("VSS = RP − EEV (EUR)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_vss_distribution(
    vss: Sequence[float],
    *,
    title: str = "Per-window out-of-sample VSS",
    xlabel: str = "VSS = RP − EEV, scored out-of-sample per window (EUR)",
) -> Figure:
    """Histogram of a per-window value metric with median and zero line (R2.5).

    The distribution is the claim: each observation is one UTC-day window's
    value (no sign guarantee), so the honest summary is the median and the
    share of windows above zero, both annotated. Serves both R2.5 per-window
    studies (VSS by default; pass ``xlabel`` for the FV variant).
    """
    values = np.asarray(vss, dtype=float)
    median = float(np.median(values))
    share_pos = float(np.mean(values > 0.0))

    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    ax.hist(values, bins=min(30, max(8, len(values) // 3)), color="#2a9d8f", alpha=0.85)
    ax.axvline(0.0, color="#e76f51", lw=1.2, ls="--", alpha=0.8, label="zero")
    ax.axvline(median, color="#264653", lw=1.6, label=f"median = {median:.2f} EUR")

    ax.set_xlabel(xlabel)
    ax.set_ylabel("windows")
    ax.set_title(f"{title}\n{len(values)} windows, {share_pos:.0%} above zero")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_value_by_regime(
    by_year: dict[int, WindowSummary],
    *,
    title: str = "Per-window value by year",
    ylabel: str = "median value per window (EUR)",
    labels: Sequence[str] | None = None,
    series: Sequence[dict[int, WindowSummary]] | None = None,
) -> Figure:
    """Per-year medians with their block-bootstrap intervals (R2.7).

    Takes the mapping ``summarize_by_year`` returns (year -> ``WindowSummary``); pass
    ``series`` plus ``labels`` to overlay several zones or studies on one axis.

    **The interval is the point of the figure.** A per-year median rests on far fewer
    windows than the pooled one, so a bare year-to-year line invites reading a trend
    into sampling noise, which is exactly the misreading R2.7's own cross-check caught.
    Drawing each year's interval puts the uncertainty in front of the reader instead.
    """
    groups = list(series) if series is not None else [by_year]
    names = list(labels) if labels is not None else [""] * len(groups)
    palette = ["#264653", "#e76f51", "#2a9d8f", "#e9c46a"]

    years = sorted({y for g in groups for y in g})
    x = np.arange(len(years), dtype=float)
    width = 0.8 / max(len(groups), 1)

    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    for k, (group, name) in enumerate(zip(groups, names, strict=False)):
        offset = (k - (len(groups) - 1) / 2.0) * width
        xs, meds, lo, hi = [], [], [], []
        for i, year in enumerate(years):
            s = group.get(year)
            if s is None:
                continue
            xs.append(x[i] + offset)
            meds.append(s.median)
            # Clamp a NaN interval (a year with one block) to the point estimate, so
            # the marker still plots and simply carries no error bar.
            lo.append(s.median - (s.median_ci[0] if s.median_ci[0] == s.median_ci[0] else s.median))
            hi.append((s.median_ci[1] if s.median_ci[1] == s.median_ci[1] else s.median) - s.median)
        ax.errorbar(
            xs, meds, yerr=[lo, hi], fmt="o", capsize=4, lw=1.4,
            color=palette[k % len(palette)], label=name or None,
        )  # fmt: skip

    ax.axhline(0.0, color="#8d99ae", lw=1.1, ls="--", alpha=0.9)
    ax.set_xticks(x)
    ax.set_xticklabels([str(y) for y in years])
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if any(names):
        ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    return fig
