"""Property tests for R2.4b — dual-grounded narration.

Contract: docs/specs/dual-narration.md § "Property tests".

The central invariant is **no unsourced number**: every numeric token the reader
sees is traceable to the solved `Explanation`. Concretely it is either a formatted
field of that object, or a period/run index the emitting claim already declared in
its `refs`. The model contributes ordering and wording only, and has no channel
through which a digit of its own can reach the reader.

The dispatch strategy mirrors tests/property/test_explain.py: feasibility is
guaranteed by soc_initial == soc_terminal, so idle is always feasible.

Failing until `bess.narrate` is implemented (test-first, R2.4b build task).
"""

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bess.assets.battery import BatterySpec, DegradationSpec
from bess.explain.duals import explain_schedule
from bess.narrate.claims import CLAIM_TYPES, Claim, Narration, holds
from bess.narrate.narrate import NarrationConfig, narrate
from bess.narrate.provider import MalformedProvider, RaisingProvider, RecordedProvider
from bess.narrate.render import fallback, render
from bess.narrate.verify import verify

_eta_solver = st.one_of(st.floats(min_value=0.8, max_value=0.9999), st.just(1.0))
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@st.composite
def explanation(draw):
    n = draw(st.integers(min_value=2, max_value=6))
    prices = draw(
        st.lists(
            st.floats(min_value=-60.0, max_value=200.0, allow_nan=False, allow_infinity=False),
            min_size=n,
            max_size=n,
        )
    )
    anchor = draw(st.one_of(st.just(0.0), st.floats(min_value=1e-3, max_value=0.9)))
    deg = draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=25.0)))
    spec = BatterySpec(
        capacity=draw(st.floats(min_value=0.5, max_value=4.0)),
        soc_min=0.0,
        p_charge_max=draw(st.floats(min_value=0.5, max_value=2.0)),
        p_discharge_max=draw(st.floats(min_value=0.5, max_value=2.0)),
        eta_charge=draw(_eta_solver),
        eta_discharge=draw(_eta_solver),
        ramp=None,
        soc_initial=anchor,
        soc_terminal=anchor,
        degradation=None if deg is None else DegradationSpec(cost_per_mwh=deg),
    )
    dt = draw(st.sampled_from([0.25, 0.5, 1.0]))
    return explain_schedule(prices, spec, dt=dt)


@st.composite
def any_claim(draw, exp):
    """A claim of any type over any index, valid or not. Feeds the totality tests."""
    kind = draw(st.sampled_from(sorted(CLAIM_TYPES)))
    hi = max(len(exp.periods), len(exp.runs)) + 1
    arity = 2 if kind == "water_value_step" else 1
    refs = draw(st.lists(st.integers(min_value=-1, max_value=hi), min_size=arity, max_size=arity))
    return Claim(type=kind, refs=refs, text="a sentence with no digits in it")


@st.composite
def valid_claims(draw, exp):
    """Every claim whose predicate holds on this explanation, with sourced placeholders."""
    out = []
    for t in range(len(exp.periods)):
        for kind, third in (
            ("threshold_cross", "band_low"),
            ("no_trade_band", "band_high"),
            ("tie_break_ambiguous", "soc"),
            ("slippage_margin", "slippage"),
        ):
            text = f"At {{time:{t}}} the price {{price:{t}}} against {{{third}:{t}}}."
            claim = Claim(type=kind, refs=[t], text=text)
            if holds(claim, exp):
                out.append(claim)
    for i in range(len(exp.runs)):
        claim = Claim(type="flat_run", refs=[i], text=f"The run holds at {{mu:{i}}}.")
        if holds(claim, exp):
            out.append(claim)
    for i in range(len(exp.runs) - 1):
        claim = Claim(
            type="water_value_step",
            refs=[i, i + 1],
            text=f"It steps from {{mu:{i}}} to {{mu:{i + 1}}}.",
        )
        if holds(claim, exp):
            out.append(claim)
    return draw(st.lists(st.sampled_from(out), min_size=1, max_size=6)) if out else []


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data(), exp=explanation())
def test_no_unsourced_number(data, exp):
    """Every numeric token in rendered output is a field value or a declared index."""
    claims = data.draw(valid_claims(exp))
    if not claims:
        return
    narration = Narration(claims=claims)
    assert verify(narration, exp) is None
    text = render(narration, exp)

    sourced = {f"{v:.2f}" for v in _field_values(exp)} | {f"{v:.3f}" for v in exp.schedule.soc}
    sourced |= {str(i) for c in claims for i in c.refs}
    for token in _NUMBER.findall(text):
        assert token in sourced, f"unsourced numeric token {token!r} in {text!r}"


def _field_values(exp):
    yield exp.schedule.objective
    for p in exp.periods:
        yield p.price_eur_mwh
        yield p.water_value_eur_mwh
        for v in (p.band_low_eur_mwh, p.band_high_eur_mwh, p.breakeven_slippage_eur_mwh):
            if v is not None:
                yield v
    for r in exp.runs:
        yield r.water_value_eur_mwh


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.data(), exp=explanation())
def test_verifier_totality(data, exp):
    """`verify` returns None or a named rule for any narration, and never raises."""
    claims = data.draw(st.lists(any_claim(exp), min_size=0, max_size=4))
    result = verify(Narration(claims=claims), exp)
    assert result is None or isinstance(result, str)


@settings(max_examples=120, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(explanation())
def test_unpinned_runs_carry_no_band_claim(exp):
    """No band-asserting claim is ever accepted on an unpinned run."""
    for i, run in enumerate(exp.runs):
        if run.pinned:
            continue
        for t in run.periods:
            for kind in ("threshold_cross", "no_trade_band"):
                claim = Claim(type=kind, refs=[t], text=f"held at {{price:{t}}}.")
                assert not holds(claim, exp), f"{kind} accepted on unpinned run {i}"


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(explanation())
def test_fallback_totality(exp):
    """Every provider failure mode yields an unverified, non-empty narrative."""
    config = NarrationConfig()
    for provider in (
        RaisingProvider(RuntimeError("transport")),
        RaisingProvider(TimeoutError("slow")),
        MalformedProvider(),
    ):
        result = narrate(exp, config=config, provider=provider)
        assert result.verified is False
        assert result.text == fallback(exp)
        assert result.rejection


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(explanation())
def test_fallback_purity(exp):
    """The fallback is a function of the explanation alone."""
    assert fallback(exp) == fallback(exp)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(explanation())
def test_a_digit_in_any_claim_rejects_the_whole_narration(exp):
    """Rule 1 fires on the narration, not on the claim: nothing partial is rendered."""
    good = Claim(type="flat_run", refs=[0], text="The run holds at {mu:0}.")
    bad = Claim(type="flat_run", refs=[0], text="The run holds at 100.00.")
    narration = Narration(claims=[good, bad])
    assert verify(narration, exp) == "digit_in_text"
    result = narrate(exp, config=NarrationConfig(), provider=RecordedProvider(narration))
    assert result.verified is False
    assert result.text == fallback(exp)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(explanation())
def test_claim_count_bounds(exp):
    """Zero claims and more than max_claims are both rejected."""
    assert verify(Narration(claims=[]), exp) == "claim_count"
    many = [Claim(type="flat_run", refs=[0], text="Held at {mu:0}.")] * 9
    assert verify(Narration(claims=many), exp, max_claims=8) == "claim_count"
