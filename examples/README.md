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
