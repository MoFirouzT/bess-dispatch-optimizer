# examples

Runnable demonstrations over the deterministic core. Both use a **synthetic**
day-ahead price series (`bess.data.fixtures.synthetic_day_ahead`); no real or
third-party market data is involved.

The plotting example needs the optional `examples` dependency group:

```bash
uv sync --group examples
```

## `worked_example.py`

Runs the walk-forward backtest (greedy / rolling / perfect-foresight) on a 90-day
synthetic series, prints the headline metrics, and regenerates the two figures the
README embeds (`docs/figures/example-dispatch-day.svg`,
`docs/figures/example-baselines.svg`).

```bash
uv run python examples/worked_example.py
```

Representative output: rolling captures ≈ 98.4% of the perfect-foresight ceiling;
annualized ceiling ≈ €28k per MWh-installed per year.

## `benchmark_scaling.py`

Times `optimizer.core.solve` (build + HiGHS solve + load) as the horizon grows from
one day to one month. No plotting dependency required.

```bash
uv run python examples/benchmark_scaling.py
```

Timings are machine-dependent; on a recent laptop the month-long (720-period) solve
is on the order of 100 ms, scaling roughly linearly in the horizon.

## `scenario_reduction_demo.py` (R2.2)

Generates a 300-path scenario set by residual-path bootstrap off a synthetic
day-ahead shape, reduces it to a sweep of kept counts with fast forward selection
(and the k-means baseline), and writes the count-vs-distance / count-vs-time
trade-off figure the R2.2 spec calls for (`docs/figures/example-scenario-reduction.svg`).
Needs the `examples` group (k-means and plotting).

```bash
uv run --group examples python examples/scenario_reduction_demo.py
```

Illustrative only (synthetic data): distance to the original set falls smoothly as
more scenarios are kept, at a reduction cost that grows with the kept count. The
k-means baseline reaches a slightly lower raw distance (its centroids are averaged
paths), while forward selection keeps genuine price paths and carries the
Kantorovich stability guarantee (ADR-0018).

## `stochastic_demo.py` (R2.3)

Builds synthetic day-ahead scenario sets and writes the two R2.3 figures: the
mean-CVaR **risk-return frontier** (expected profit vs downside as the risk weight
λ sweeps, `docs/figures/example-risk-return-frontier.svg`) and the **VSS curve**
(value of the stochastic solution vs the recourse budget ρ,
`docs/figures/example-vss-curve.svg`). Needs the `examples` group (plotting).

```bash
uv run --group examples python examples/stochastic_demo.py
```

Illustrative only (synthetic data): the frontier trades expected profit for lower
downside as risk aversion grows; the VSS rises from 0 (no recourse) to a positive
interior and falls back toward 0 (unlimited recourse) — the escape from the VSS = 0
trap, with a finite budget the source of value (§R2.3, ADR-0019/0020).
