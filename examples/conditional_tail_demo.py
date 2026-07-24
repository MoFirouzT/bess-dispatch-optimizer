#!/usr/bin/env python3
"""Residual-load-conditional tail demo (R2.2c) — spike size vs residual load.

Builds synthetic forecast residuals whose spikes are correlated with residual load
(scarcity spikes on tight-margin hours), fits the conditional GPD scale β(x), and
plots the exceedances against residual load with the rising conditional scale over
the flat unconditional one. Synthetic by design (the no-committed-data rule);
numbers illustrative, not a gate. Run:

    uv run python examples/conditional_tail_demo.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bess.scenarios.tail import ConditionalTailModel, TailModel

FIG = Path(__file__).resolve().parent.parent / "docs" / "figures" / "example-conditional-tail.svg"
N_DAYS = 400


def main() -> None:
    rng = np.random.default_rng(3)
    hours = 24
    # Synthetic residual load: a daily shape (tight evenings, slack nights) plus noise.
    base_rl = 9000 + 4000 * np.sin((np.arange(hours) - 8) / 24 * 2 * np.pi)
    rl = base_rl[None, :] + rng.normal(0, 800, size=(N_DAYS, hours))

    # Price residuals: mostly small, but spikes whose size grows with residual load,
    # so β(x) genuinely rises (a mechanism demo of the conditional effect).
    residuals = rng.normal(0, 8, size=(N_DAYS, hours))
    z = (rl - rl.mean()) / rl.std()
    spike = rng.random((N_DAYS, hours)) < 0.05
    residuals[spike] += rng.exponential(15.0 * np.exp(0.6 * z[spike]))

    model = ConditionalTailModel.fit(residuals, rl, threshold_quantile=0.95, side="upper")
    uncond = TailModel.fit(residuals, threshold_quantile=0.95, side="upper")

    r = residuals.ravel()
    x = rl.ravel()
    u = model.threshold
    mask = r > u
    exc = r[mask] - u
    exc_rl = x[mask]

    grid = np.linspace(exc_rl.min(), exc_rl.max(), 100)
    beta_grid = model.beta_at(grid)

    print("R2.2c conditional-tail demo (synthetic)\n")
    print(f"  gamma           : {model.gamma:.3f}  (log-scale slope on residual load)")
    print(f"  xi / beta0      : {model.xi:.3f} / {model.beta0:.2f}")
    print(f"  unconditional β : {uncond.beta:.2f}")
    print(
        f"  β(x): slack {model.beta_at(np.array([grid[0]]))[0]:.1f} "
        f"-> tight {model.beta_at(np.array([grid[-1]]))[0]:.1f} €/MWh"
    )

    from bess.viz.backtest_plots import plot_conditional_tail

    fig = plot_conditional_tail(
        exc_rl.tolist(),
        exc.tolist(),
        grid.tolist(),
        beta_grid.tolist(),
        float(uncond.beta),
        gamma=model.gamma,
    )
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, format="svg", bbox_inches="tight")
    print(f"\nwrote {FIG.relative_to(FIG.parent.parent.parent)}")


if __name__ == "__main__":
    main()
