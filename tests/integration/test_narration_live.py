"""Integration — R2.4b: how often does a real model produce a narration that verifies?

Contract: docs/specs/dual-narration.md § "Acceptance gate", the live tier.

This is the only test in the suite that calls a language model, and it is the only
place the R2.4b design is exercised end to end. Everything the phase *gates* runs
offline against injected providers, because the model's output is not reproducible:
`temperature` and `top_p` are rejected on Claude Opus 5, so two identical requests may
differ and an assertion on the text would be an assertion on luck.

What is measured here is one number: the fraction of real dispatches whose narration
is rejected. The adoption bar was set in the spec, before any call was made, at **5%**.
Above it, the narrative endpoint does not ship, the verifier and fallback stay, and
the measured rate is the finding.

Credential-gated on `ANTHROPIC_API_KEY` and `integration`-marked, so CI never reaches
it. Each run costs real money, which is why the instance count is a floor rather than
a sweep.
"""

from __future__ import annotations

import collections
import os
import time

import pytest

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.data.fixtures import synthetic_day_ahead
from bess.explain.duals import DualityError, explain_schedule
from bess.narrate.narrate import NarrationConfig, narrate

pytestmark = pytest.mark.integration

requires_credential = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — live narration test skipped (never runs in CI)",
)

# The spec's adoption bar, recorded before the first live call (spec decision 5).
ADOPTION_BAR = 0.05
INSTANCES = 50

# The serving default is 10 s, and one measured call took 11.5 s, so at the shipped
# timeout this tier would count timeouts rather than claim quality. It is raised here
# so the instrument can observe the thing the bar is about; the latency it records is
# reported separately, because a 10 s serving budget the model cannot meet is its own
# finding and not one this test should hide by asserting on it.
LIVE_CONFIG = NarrationConfig(timeout_s=90.0)

SPEC = BatterySpec(
    capacity=2.0,
    p_charge_max=1.0,
    p_discharge_max=1.0,
    eta_charge=0.95,
    eta_discharge=0.95,
    soc_initial=0.5,
    soc_terminal=0.5,
    degradation=DegradationSpec(cost_per_mwh=5.0),
)


def _instances(n: int):
    """`n` day-long dispatches, one per day of the seeded day-ahead generator.

    Synthetic rather than real prices, for two reasons: no market data is committed
    (docs/decisions/no-committed-market-data.md), and the question this tier asks is
    whether the model can describe a *dispatch structure* under the placeholder rule,
    which does not turn on price realism. The generator carries the diurnal shape the
    dispatch reacts to, which is the part that matters here.
    """
    series = synthetic_day_ahead(days=n + 20, seed=11)
    made = 0
    day = 0
    while made < n and (day + 1) * 24 <= len(series):
        prices = [float(v) for v in series.iloc[day * 24 : (day + 1) * 24]]
        day += 1
        try:
            exp = explain_schedule(prices, SPEC, dt=1.0)
        except (DualityError, RuntimeError):
            continue  # not a narration outcome; skip without consuming the count
        made += 1
        yield day - 1, exp


@requires_credential
def test_live_rejection_rate_against_the_adoption_bar():
    """Record the rejection rate and its rule breakdown, then hold it to the bar."""
    rejected: collections.Counter[str] = collections.Counter()
    latencies: list[float] = []
    total = 0
    for _day, exp in _instances(INSTANCES):
        started = time.monotonic()
        result = narrate(exp, config=LIVE_CONFIG)
        latencies.append(time.monotonic() - started)
        total += 1
        if not result.verified:
            rejected[result.rejection or "unknown"] += 1

    rate = sum(rejected.values()) / total
    latencies.sort()
    print(f"\nR2.4b live tier: {total} instances, rejection rate {rate:.1%}")
    for rule, count in rejected.most_common():
        print(f"  {rule}: {count}")
    print(
        f"  latency s: min {latencies[0]:.1f} median {latencies[len(latencies) // 2]:.1f} "
        f"max {latencies[-1]:.1f} (serving default is {NarrationConfig().timeout_s:.0f})"
    )

    assert total == INSTANCES
    assert rate < ADOPTION_BAR, (
        f"rejection rate {rate:.1%} is at or above the {ADOPTION_BAR:.0%} adoption bar; "
        "the narrative endpoint does not ship and the rate is the finding "
        "(docs/specs/dual-narration.md, acceptance gate)"
    )


@requires_credential
def test_a_verified_narration_contains_no_number_the_model_wrote():
    """The central invariant, once, against the real model rather than a fixture."""
    _day, exp = next(iter(_instances(1)))
    result = narrate(exp, config=LIVE_CONFIG)
    if not result.verified:
        pytest.skip(f"model output was rejected ({result.rejection}); see the rate test")
    sourced = {f"{p.price_eur_mwh:.2f}" for p in exp.periods}
    sourced |= {f"{r.water_value_eur_mwh:.2f}" for r in exp.runs}
    sourced |= {f"{exp.schedule.objective:.2f}"}
    # `soc` is one of the eight placeholders and renders at three decimals, not two
    # (`render.resolve`). Omitting it here made this oracle incomplete rather than
    # strict: the 2026-09-04 live run failed on `2.000`, a state of charge the solver
    # produced and the renderer substituted, which rule 1 (`digit_in_text`) forbids the
    # model from having written. Every placeholder the renderer can emit belongs here.
    sourced |= {f"{v:.3f}" for v in exp.schedule.soc}
    sourced |= {
        f"{v:.2f}"
        for p in exp.periods
        for v in (p.band_low_eur_mwh, p.band_high_eur_mwh, p.breakeven_slippage_eur_mwh)
        if v is not None
    }
    sourced |= {str(i) for i in range(max(len(exp.periods), len(exp.runs)))}
    import re

    for token in re.findall(r"-?\d+(?:\.\d+)?", result.text):
        assert token in sourced, f"unsourced token {token!r} in live output: {result.text!r}"
