# Solve scaling: does the program stay tractable?

**Answer: yes on both axes, at very different rates.** The deterministic program
grows mildly with the horizon; the two-stage program grows with the scenario
count, which is precisely the cost that scenario reduction keeps bounded.

## The question

Two separate things can make this stack too slow to serve: a long horizon, and a
large scenario set. They scale differently and are worth measuring separately.

## Result

The deterministic program adds one binary and a few continuous variables per
period, so it grows benignly in the horizon:

| Deterministic | Periods | Median solve |
| --- | --- | --- |
| 1 day | 24 | ~9 ms |
| 1 week | 168 | ~29 ms |
| 1 month | 720 | ~120 ms |

The two-stage program carries S + 1 coupled copies of the physics, so the
scenario count is the expensive axis:

| Two-stage, 24 h | Binaries | Median solve |
| --- | --- | --- |
| 10 scenarios | 264 | ~0.5 s |
| 30 scenarios | 744 | ~1.0 s |
| 50 scenarios | 1,224 | ~2.0 s |

Numbers are from a local run, so treat them as relative rather than absolute.

## Why this justifies the reduction step

Scenario generation produces a few hundred paths and forward-selection reduction
keeps roughly 50 of them within a Kantorovich tolerance. The second table is why
that step exists: without it the stochastic program would carry several hundred
coupled copies of the physics, and the serving path has a latency budget measured
in seconds.

![Scenario reduction: Kantorovich distance to the full set against the number of paths kept, beside the wall-clock cost of reducing.](../figures/example-scenario-reduction.svg)

The reduction figure is synthetic by design: it demonstrates the algorithm's
trade-off, not a market result.

The bid-curve study is the one place this budget bites. Its monotonicity chain
couples every commitment branch, so it runs at 10 scenarios rather than 30, which
is a [stated limitation](bid-curves.md) of that study.

## Reproduce

```bash
uv run python examples/benchmark_scaling.py
```

No plotting dependency required.
