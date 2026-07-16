#!/usr/bin/env python3
"""Drift-monitor demo (R2.1b) — attribution regions, not a single alarm.

A forecaster that degrades is not automatically at fault: the market may have moved
(a *regime shift*, where a naive baseline degrades too) or the model may have decayed
relative to naive (*staleness*, the retrain signal), or the point forecast may be fine
while the intervals stopped covering (*miscalibration*, the recalibrate signal). The
R2.1b monitor separates these so the flag is actionable.

This draws the classifier's decision map over its two continuous axes, the error ratio
(forecaster MAE / seasonal-naive MAE) and the input shift (PSI). Every cell's colour is
the status the **real** ``classify_drift`` returns there, so the regions are the code's,
not drawn by hand. Labelled example windows sit on the map. Miscalibration is driven by
a third axis (interval coverage) this 2-D map cannot show, so its example window sits
inside the healthy region, which is exactly the point: the ratio/PSI view alone would
miss it.

Synthetic by design (a mechanism demo like the ingestion guard and scenario reduction,
not a market result), so it needs no token. Needs the ``examples`` group (matplotlib);
``classify_drift`` itself is pure numpy. Run:

    uv run --group examples python examples/drift_demo.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bess.forecaster.drift import (
    DEFAULT_PSI_WARN,
    DEFAULT_STALENESS_RATIO,
    DriftStatus,
    classify_drift,
)

GRID_N = 80  # mesh resolution per axis (the smoke test shrinks this)
FIG = Path(__file__).resolve().parent.parent / "docs" / "figures" / "example-drift-regions.svg"

# Status → (code, legend label, colour). Only the three the ratio/PSI map can show are
# shaded; miscalibration (coverage-driven) appears as an annotated point below.
_CODE = {
    DriftStatus.HEALTHY: (0, "healthy", "#2a9d8f"),
    DriftStatus.REGIME_SHIFT: (1, "regime shift (wait)", "#e9c46a"),
    DriftStatus.STALENESS: (2, "staleness (retrain)", "#e76f51"),
}

# Example windows (ratio, psi, label) — illustrative, placed to land one in each region.
# The miscalibration window sits in the healthy region on purpose (see the module note).
POINTS = [
    (0.80, 0.13, "healthy"),
    (1.05, 0.34, "regime shift → wait"),
    (1.58, 0.10, "staleness → retrain"),
    (0.98, 0.04, "miscalibration → recalibrate"),
]


def main() -> None:
    ratios = np.linspace(0.6, 2.0, GRID_N)
    psis = np.linspace(0.0, 0.5, GRID_N)

    # Colour each cell by the real classifier (coverage=None, so miscalibration, which
    # keys on coverage, never shades the map — it is the orthogonal third axis).
    codes = np.empty((GRID_N, GRID_N), dtype=int)
    for j, psi_value in enumerate(psis):
        for i, ratio in enumerate(ratios):
            report = classify_drift(
                forecaster_mae=float(ratio), naive_mae=1.0, psi_value=float(psi_value)
            )
            codes[j, i] = _CODE[report.status][0]

    present = sorted({int(c) for c in codes.ravel()})
    legend = [(code, label, color) for _, (code, label, color) in _CODE.items() if code in present]

    counts = {label: int((codes == code).sum()) for code, label, _ in legend}
    print("Drift attribution map (mechanism demo)\n")
    print(f"staleness threshold ratio ≥ {DEFAULT_STALENESS_RATIO}, PSI warn ≥ {DEFAULT_PSI_WARN}\n")
    for label, n in counts.items():
        print(f"  {label:<24} {n:>6} cells")

    from bess.viz.forecast_plots import plot_drift_regions

    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig = plot_drift_regions(
        ratios, psis, codes, legend,
        points=POINTS,
        staleness_ratio=DEFAULT_STALENESS_RATIO,
        psi_warn=DEFAULT_PSI_WARN,
    )  # fmt: skip
    fig.savefig(FIG, format="svg", bbox_inches="tight")
    print(f"\nwrote {FIG.name} to docs/figures/")


if __name__ == "__main__":
    main()
