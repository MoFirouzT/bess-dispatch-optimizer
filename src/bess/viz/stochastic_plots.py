"""Reproducible R2.3 figures exported to ``docs/figures/`` (no new math).

- :func:`plot_risk_return_frontier` — the mean-CVaR frontier: expected profit
  against downside (loss CVaR) as the risk weight λ sweeps 0 → 1;
- :func:`plot_vss_curve` — the value of the stochastic solution against the
  recourse budget ρ, showing VSS = 0 at both limits and a positive interior.

``matplotlib`` is an optional dependency (the ``examples`` group); importing this
module without it raises a clear ``ImportError``. ``viz`` sits outside the serving
chain and is not part of any import-linter contract.
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
