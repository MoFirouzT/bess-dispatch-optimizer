# examples

Runnable scripts, split by what they are for. **`quickstart.py`** is the front door
and runs on the base install. **Studies** measure something and report a number; their
findings are written up in [`docs/studies/`](../docs/studies/). **Demonstrations**
render a mechanism and regenerate a committed figure.

Scripts marked "token" use real ENTSO-E prices when `ENTSOE_API_TOKEN` is set and
fall back to a synthetic series otherwise; the rest are synthetic by design. No
real or third-party market data is committed.

Most plotting scripts need the optional dependency group:

```bash
uv sync --group examples
```

---

# Start here

## `quickstart.py`

The whole stack in one command, on the **base install**: no ENTSO-E token, no optional
dependency group, no plotting. It solves one day, bounds that schedule between the
greedy floor and the perfect-foresight ceiling over a month, prints the water value and
no-trade band that explain a hold, and catches a frozen price feed.

```bash
uv sync
uv run python examples/quickstart.py
```

Runs in about two seconds on synthetic prices, so its numbers are illustrative. The
real-data equivalents are `worked_example.py` and the studies below.

---

# Studies

## `vss_study.py` (token)

The per-window out-of-sample VSS and forecast-value distributions over real days,
plus the per-year regime view, and the three figures the README and studies pages
embed. Needs the `forecast` group for the forecast-value half.

Two modes, because scoring all 260 delivery days takes about fifteen minutes:

```bash
uv run --group examples python examples/vss_study.py              # fast (default)
uv run --group examples python examples/vss_study.py --mode full  # the committed figures
```

`fast` strides across the fold blocks, so it still spans 2022 to 2025 rather than
truncating to one regime, and writes to `build/figure-previews/`. **Only `--mode full`
writes to `docs/figures/`**: a figure built from a subsample must not be committable
over a published one, so the output path enforces it rather than a console warning.

Write-ups: [stochastic value](../docs/studies/stochastic-value.md),
[forecast value](../docs/studies/forecast-value.md).

## `duration_sweep.py` (token)

Sweeps storage duration over {1 h, 2 h, 4 h} and reports the annualized ceiling
per MWh installed, plus the capture ratio at each.

```bash
uv run --group examples python examples/duration_sweep.py
```

Write-up: [storage duration](../docs/studies/storage-duration.md).

## `benchmark_scaling.py`

Times `optimizer.core.solve` (build + HiGHS solve + load) as the horizon grows from
one day to one month. No plotting dependency required.

```bash
uv run python examples/benchmark_scaling.py
```

Timings are machine-dependent; on a recent laptop the month-long (720-period) solve
is on the order of 100 ms, scaling roughly linearly in the horizon.
Write-up: [solve scaling](../docs/studies/solve-scaling.md).

---

# Demonstrations

## `worked_example.py` (token)

Runs the walk-forward backtest (greedy / rolling / perfect-foresight), prints the
headline baseline numbers, and regenerates the dispatch figure the README embeds
(`docs/figures/example-dispatch-day.svg`). The baseline comparison is reported as
numbers, not plotted.

```bash
uv run python examples/worked_example.py
```

Representative output: rolling captures ≈ 98.4% of the perfect-foresight ceiling;
annualized ceiling ≈ €28k per MWh-installed per year.

## `forecast_demo.py` (token)

Fits the conformal price forecaster and writes the calibrated-interval figure
(`docs/figures/example-forecast-intervals.svg`). Needs the `forecast` group.

```bash
uv run --group forecast --group examples python examples/forecast_demo.py
```

## `drift_demo.py`

Renders the drift monitor's decision regions over the error ratio and input shift
(`docs/figures/example-drift-regions.svg`). Synthetic by design: it shows the
classifier's geometry, not a market result.

```bash
uv run --group examples python examples/drift_demo.py
```

## `scenario_reduction_demo.py`

Generates a 300-path scenario set by residual-path bootstrap off a synthetic
day-ahead shape, reduces it to a sweep of kept counts with fast forward selection
(and the k-means baseline), and writes the count-vs-distance / count-vs-time
trade-off figure (`docs/figures/example-scenario-reduction.svg`). Needs the
`examples` group (k-means and plotting).

```bash
uv run --group examples python examples/scenario_reduction_demo.py
```

Illustrative only (synthetic data): distance to the original set falls smoothly as
more scenarios are kept, at a reduction cost that grows with the kept count. The
k-means baseline reaches a slightly lower raw distance (its centroids are averaged
paths), while forward selection keeps genuine price paths and carries the
Kantorovich stability guarantee ([forward selection over k-means](../docs/decisions/forward-selection-over-kmeans.md)).

## `stochastic_demo.py` (token)

Writes the two risk figures: the mean-CVaR **risk-return frontier** (expected
profit vs downside as the risk weight sweeps,
`docs/figures/example-risk-return-frontier.svg`) and the **VSS curve** (value of
the stochastic solution vs the recourse budget,
`docs/figures/example-vss-curve.svg`). Needs the `examples` group (plotting).

```bash
uv run --group examples python examples/stochastic_demo.py
```

The frontier trades expected profit for lower downside as risk aversion grows; the
VSS rises from 0 (no recourse) to a positive interior and falls back toward 0
(unlimited recourse), which is the escape from the VSS = 0 trap, with a finite
budget the source of value ([the risk-aware two-stage design](../docs/decisions/risk-aware-two-stage-design.md)).

## `spike_tail_demo.py` and `conditional_tail_demo.py`

Fit the extreme-value scenario tail and its residual-load-conditional variant, and
write `docs/figures/example-spike-tail.svg` and
`docs/figures/example-conditional-tail.svg`. Both synthetic by design: they
demonstrate the tail mechanism, not a market result.

```bash
uv run --group examples python examples/spike_tail_demo.py
uv run --group examples python examples/conditional_tail_demo.py
```

## `explain_demo.py`

Renders the water value and the no-trade band over a day
(`docs/figures/example-water-value.svg`). Synthetic by design: it demonstrates the
dual mechanism, not a market result.

```bash
uv run --group examples python examples/explain_demo.py
```

## `ingestion_guard_demo.py`

Feeds the guard a frozen price series, shows it rejected, and dispatches on the
last-known-good series instead (`docs/figures/example-ingestion-guard.svg`).

```bash
uv run --group examples python examples/ingestion_guard_demo.py
```
