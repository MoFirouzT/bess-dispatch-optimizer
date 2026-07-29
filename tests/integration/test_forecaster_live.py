"""Integration — R2.1 forecaster coverage on real ENTSO-E prices, walk-forward.

Contract: docs/specs/price-forecaster.md § "Gates",
docs/specs/forecaster-evaluation.md § "Acceptance gate", and
docs/specs/target-normalization.md § "Acceptance gate".

**What R2.1d changed here.** The original gate trained and tested inside a single
Feb-to-Jun 2024 window and took the last 15 days as three contiguous folds, so every
number it produced was a statement about one fortnight of one zone. It also ran a
60-tree model while the shipped default is 200, and it checked coverage against a
fixed ``0.9 ± 0.05`` band whose width was narrower than the sampling noise of the
statistic it gated. This module now evaluates across **2021 to 2025**, spreads folds
over the whole span with a fixed-length rolling training window, runs the **shipped**
model capacity, and decides on a **day-block bootstrap interval** rather than on a
point estimate.

The decision rule is deliberately the weaker-looking one: the gate fails only when
the whole interval lies outside ``[0.85, 0.95]``, that is, only when the data can
rule out the tolerance claim. It gets *stronger* as the span grows, because a
narrower interval is harder to overlap with the band when coverage is genuinely off.

Doubly gated: needs both the `forecast` dependency group (LightGBM + MAPIE) and a
token. `importorskip` skips cleanly when the group is absent (so the main CI job,
synced without the group, never errors at collection); the `integration` marker +
`ENTSOE_API_TOKEN` skip/deselect keep it off every CI job. Nothing fetched here is
committed. Run locally with: `uv run --group forecast pytest
tests/integration/test_forecaster_live.py -s` (token loaded).

**What R2.1e added.** The conditional-coverage axis: coverage *per hour of day*, the
property docs/decisions/cqr-over-split-conformal.md chose CQR for and which nothing had ever tested.
R2.1e's normalized
target is gated here against the raw model on identical folds, null-tolerantly. The
cyclical season encoding and the rolling-stat features were measured and deliberately
**not** shipped (see the R2.1e spec § "Measured results"), so the shipped model here
differs from R2.1d only in the quantile-crossing fix.

Network setup (this machine): a TLS-intercepting proxy means uv-Python may need the
Keychain roots — see docs/specs/data-feed.md § "Environment note".
"""

import os

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("mapie")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from span import WALK_FORWARD, span_prices  # noqa: E402

from bess.data.entsoe import fetch_day_ahead  # noqa: E402
from bess.data.ingestion_guard import FeedStatus, guarded_fetch  # noqa: E402
from bess.forecaster.evaluate import (  # noqa: E402
    walk_forward_coverage,
    walk_forward_pinball_skill,
)
from bess.forecaster.forecast import PriceForecaster  # noqa: E402

pytestmark = pytest.mark.integration

requires_token = pytest.mark.skipif(
    not os.environ.get("ENTSOE_API_TOKEN"),
    reason="ENTSOE_API_TOKEN not set — live ENTSO-E integration test skipped (never runs in CI)",
)

_WF = dict(WALK_FORWARD)

#: No capacity override: the gated model is the shipped model (R2.1d build task).
_SEED = dict(random_state=0)

#: The R2.1 coverage tolerance band, now tested by interval overlap rather than by a
#: point estimate falling inside it.
_GATE_BAND = (0.85, 0.95)

_TRAIN_WINDOW = (pd.Timestamp("2024-02-01", tz="UTC"), pd.Timestamp("2024-06-01", tz="UTC"))
#: A season the training window does not reach: NL late autumn / winter. Deliberately
#: disjoint and *later*, so no lag can bridge the two windows.
_WINTER_WINDOW = (pd.Timestamp("2024-11-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC"))


def _guarded_prices(window, zone="NL"):
    """Fetch a window through the R1.4c guard, hard-stopping on a degraded feed."""
    result = guarded_fetch(lambda: fetch_day_ahead(zone, *window), last_known_good=None)
    assert result.status is FeedStatus.HEALTHY, f"real {zone} feed classified {result.status.value}"
    assert result.degraded is False
    return result.prices


def _overlaps(ci, band):
    """Do the interval and the tolerance band share any point?"""
    return ci[0] <= band[1] and band[0] <= ci[1]


@requires_token
@pytest.mark.parametrize("method", ["cqr", "split"])
def test_coverage_interval_does_not_rule_out_the_tolerance_band(method):
    """The headline gate, restated across seasons and reported with its uncertainty.

    Coverage is pooled over every fold and reported with a day-block bootstrap
    interval, because the effective sample is the evaluated **day** count, not the
    hour count. See `conftest.span_prices` for why this particular fetch does not run through
    the R1.4c guard, and what was measured to establish that.
    """
    prices = span_prices("NL")

    res = walk_forward_coverage(
        prices, confidence_level=0.9, method=method, return_detail=True, **_WF, **_SEED
    )

    print(
        f"\nR2.1d coverage (NL 2021-2025, {res.n_test_days} test days, {method}):"
        f"\n  coverage={res.coverage:.3f}  95% CI=[{res.ci_low:.3f}, {res.ci_high:.3f}]"
        f"  mean width={res.mean_width:.1f} EUR/MWh"
        f"\n  per-fold min/max={min(res.per_fold):.3f}/{max(res.per_fold):.3f}"
    )

    assert res.mean_width > 0.0
    assert res.n_test_days >= 250, "fewer evaluated days than the fold plan implies"
    assert _overlaps((res.ci_low, res.ci_high), _GATE_BAND), (
        f"{method}: the 95% interval [{res.ci_low:.3f}, {res.ci_high:.3f}] lies wholly "
        f"outside {_GATE_BAND}, so the data rules out the R2.1 tolerance claim on this "
        f"span (point estimate {res.coverage:.3f})"
    )


@requires_token
def test_intervals_are_sharper_than_the_seasonal_naive_baseline():
    """Coverage alone is satisfiable by predicting plus or minus infinity.

    R2.1 gated coverage and asserted only `width > 0`, so nothing in the suite
    separated a calibrated forecaster from a merely wide one. This is the missing
    efficiency axis: pinball loss at both interval edges, against the seasonal-naive
    baseline, on the same folds as the coverage gate.
    """
    prices = span_prices("NL")

    skill = walk_forward_pinball_skill(prices, confidence_level=0.9, method="cqr", **_WF, **_SEED)

    print(
        f"\nR2.1d sharpness (NL 2021-2025, cqr):"
        f"\n  conformal lower/upper = {skill.conformal_lower:.3f} / {skill.conformal_upper:.3f}"
        f"\n  naive     lower/upper = {skill.naive_lower:.3f} / {skill.naive_upper:.3f}"
        f"\n  skill     lower/upper = {skill.skill_lower:.3f} / {skill.skill_upper:.3f}"
    )

    assert skill.skill_lower < 1.0, (
        f"lower-edge pinball skill {skill.skill_lower:.3f} does not beat seasonal naive"
    )
    assert skill.skill_upper < 1.0, (
        f"upper-edge pinball skill {skill.skill_upper:.3f} does not beat seasonal naive"
    )


@requires_token
def test_coverage_generalizes_to_a_second_zone():
    """A reduced generality check on BE: the same wrapper, a different market.

    Reduced by design (R2.1d open question 3): coverage only, default configuration,
    so the live tier stays inside a few minutes. NL alone cannot distinguish "the
    conformal wrapper is correct" from "NL happens to be benign".
    """
    prices = span_prices(zone="BE")

    res = walk_forward_coverage(
        prices, confidence_level=0.9, method="cqr", return_detail=True, **_WF, **_SEED
    )

    print(
        f"\nR2.1d coverage (BE 2021-2025, {res.n_test_days} test days, cqr):"
        f"  coverage={res.coverage:.3f}  95% CI=[{res.ci_low:.3f}, {res.ci_high:.3f}]"
    )

    assert _overlaps((res.ci_low, res.ci_high), _GATE_BAND), (
        f"BE: the 95% interval [{res.ci_low:.3f}, {res.ci_high:.3f}] lies wholly outside "
        f"{_GATE_BAND} (point estimate {res.coverage:.3f})"
    )


@requires_token
@pytest.mark.parametrize("method", ["cqr", "split"])
def test_coverage_gate_does_not_transfer_out_of_season(method):
    """A **stale** fit carried across a season boundary under-covers. Pinned.

    Kept unchanged through R2.1d (open question 4): it measures a model left alone
    across a season boundary, which stays true and stays worth pinning. Two causes,
    and the second is the one that bites:
      * the price regime itself moves (train mean/std 62.87/35.69 EUR/MWh, Nov-Dec
        110.59/68.25), so intervals calibrated on the calmer season are too narrow; and
      * `month` is a plain numeric feature, so a tree trained on months 2-6 can only
        split inside that range. At month=12 every split resolves the same way it would
        in June, and the model has no representation of winter at all.

    The companion test below measures the documented *response* to this, which is
    rolling recalibration rather than a retrain. Together they state the limitation
    and its mitigation; this one alone would overstate the problem.

    **If it starts failing because coverage rose into the band, that is good news and
    not a broken test** — it means the seasonal limitation was fixed at the model
    level, and the honest response is to update the README/spec claim rather than to
    loosen this assertion.
    """
    train = _guarded_prices(_TRAIN_WINDOW)
    winter = _guarded_prices(_WINTER_WINDOW)

    # The two windows really are disjoint, and winter really is a different regime;
    # without both, the under-coverage below would prove nothing.
    assert train.index[-1] < winter.index[0]
    assert winter.mean() > 1.5 * train.mean()

    forecaster = PriceForecaster(confidence_level=0.9, method=method, **_SEED).fit(train)
    forecast = forecaster.predict_interval(winter)
    realized = winter.loc[forecast.point.index]
    coverage = float(((realized >= forecast.lower) & (realized <= forecast.upper)).mean())

    print(f"\nR2.1d out-of-season, stale fit ({method}): coverage={coverage:.3f}")

    assert len(realized) > 1000, "winter block too short to read a coverage rate from"
    assert coverage < _GATE_BAND[0], (
        f"{method}: out-of-season coverage {coverage:.3f} now reaches the in-season "
        f"gate band {_GATE_BAND} — the seasonal limitation this test pins may be "
        "fixed; re-check the R2.1 coverage claim instead of relaxing this bound"
    )


@requires_token
@pytest.mark.parametrize("method", ["cqr", "split"])
def test_rolling_recalibration_recovers_out_of_season_coverage(method):
    """The documented response to under-coverage, measured rather than assumed.

    `bess.forecaster.drift` classifies under-covering intervals as MISCALIBRATION and
    prescribes "recalibrate, don't retrain". Until R2.1d nothing measured that path:
    the suite pinned the failure of a posture nobody would run in production (a fit
    left untouched across a season) and never measured the one they would.

    Here the base learners stay frozen at the June fit and only the conformal
    quantile is refreshed, on a trailing 28-day window, rolling one day at a time
    across the winter block. The gate is that this **materially improves** coverage
    over the stale fit. It is deliberately not asserted to reach the band: paying for
    coverage in width is real, and whether it fully closes a regime gap is a finding,
    not a requirement.
    """
    train = _guarded_prices(_TRAIN_WINDOW)
    winter = _guarded_prices(_WINTER_WINDOW)

    forecaster = PriceForecaster(confidence_level=0.9, method=method, **_SEED).fit(train)

    # Stale baseline on the same evaluated days, so the comparison is like for like.
    stale = forecaster.predict_interval(winter)

    trailing = pd.Timedelta(days=28)
    norm = pd.DatetimeIndex(winter.index).normalize()
    eval_days = sorted(norm.unique())[28:]  # need a full trailing window before day one

    hits, widths, stale_hits = [], [], []
    for day in eval_days:
        recent = winter[(norm >= day - trailing) & (norm < day)]
        forecaster.recalibrate(recent)
        block = winter[norm <= day]
        fc = forecaster.predict_interval(block)
        mask = pd.DatetimeIndex(fc.point.index).normalize() == day
        targets = fc.point.index[mask]
        y = winter.loc[targets].to_numpy()
        hits.append((y >= fc.lower[mask].to_numpy()) & (y <= fc.upper[mask].to_numpy()))
        widths.append(float((fc.upper[mask] - fc.lower[mask]).mean()))
        stale_hits.append(
            (y >= stale.lower.loc[targets].to_numpy()) & (y <= stale.upper.loc[targets].to_numpy())
        )

    recal_cov = float(np.concatenate(hits).mean())
    stale_cov = float(np.concatenate(stale_hits).mean())
    stale_width = float((stale.upper - stale.lower).mean())

    print(
        f"\nR2.1d rolling recalibration ({method}, 28-day trailing, {len(eval_days)} days):"
        f"\n  stale fit   coverage={stale_cov:.3f}  width={stale_width:.1f}"
        f"\n  recalibrated coverage={recal_cov:.3f}  width={np.mean(widths):.1f}"
    )

    assert recal_cov > stale_cov + 0.02, (
        f"{method}: rolling recalibration moved coverage {stale_cov:.3f} -> "
        f"{recal_cov:.3f}, not a material recovery; the drift module's documented "
        "'recalibrate, don't retrain' response does not work on this regime shift"
    )


# --- R2.1e: conditional coverage and the normalized target --------------------

#: The R2.1e model. `normalize_target` only; the cyclical season encoding and the
#: rolling-stat features were measured and are NOT shipped (see the module note below).
_NORMALIZED = dict(normalize_target=True)


@requires_token
def test_normalization_does_not_worsen_conditional_coverage():
    """The R2.1e headline gate: coverage *conditional on hour of day*.

    Conformal prediction guarantees only **marginal** coverage, so a forecaster can sit
    exactly on nominal overall while over-covering calm nights and under-covering
    volatile evening peaks. That is the property docs/decisions/cqr-over-split-conformal.md chose
    CQR for, and until
    R2.1e nothing measured it. R2.1d exposed the symptom from the other side: pooled
    coverage 0.900 with per-fold coverage running 0.617 to 1.000.

    Null-tolerant, in the R2.1c / R2.5 style: normalization must **improve or tie**.
    A measured null is a pass and is recorded as a finding; only a material worsening
    fails. Both arms run on identical folds so the comparison is like for like.
    """
    prices = span_prices("NL")

    raw = walk_forward_coverage(
        prices, confidence_level=0.9, method="cqr", return_detail=True, **_WF, **_SEED
    )
    norm = walk_forward_coverage(
        prices,
        confidence_level=0.9,
        method="cqr",
        return_detail=True,
        **_WF,
        **_SEED,
        **_NORMALIZED,
    )

    print(
        f"\nR2.1e conditional coverage (NL 2021-2025, {raw.n_test_days} test days, cqr):"
        f"\n  raw        : coverage={raw.coverage:.4f} max hour dev={raw.max_hour_deviation:.4f}"
        f"  width={raw.mean_width:.1f}"
        f"\n  normalized : coverage={norm.coverage:.4f} max hour dev={norm.max_hour_deviation:.4f}"
        f"  width={norm.mean_width:.1f}"
        f"\n  by hour (raw)  : {' '.join(f'{h:.2f}' for h in raw.by_hour)}"
        f"\n  by hour (norm) : {' '.join(f'{h:.2f}' for h in norm.by_hour)}"
    )

    # Marginal coverage must still survive, decided on the interval as in R2.1d.
    assert _overlaps((norm.ci_low, norm.ci_high), _GATE_BAND), (
        f"normalized coverage interval [{norm.ci_low:.3f}, {norm.ci_high:.3f}] lies "
        f"wholly outside {_GATE_BAND}"
    )
    # Improve or tie. The tolerance admits a null, not a regression.
    assert norm.max_hour_deviation <= raw.max_hour_deviation + 0.02, (
        f"normalization worsened hour-of-day coverage: max deviation "
        f"{raw.max_hour_deviation:.4f} -> {norm.max_hour_deviation:.4f}"
    )


@requires_token
def test_normalization_narrows_but_does_not_close_the_season_gap():
    """R2.1e open question 4, resolved by measurement: it helps, and it is not enough.

    The pin above measures a stale fit carried across a season boundary. If R2.1e had
    lifted that coverage into the band, the pin would have done its job and been
    rewritten to assert the improvement. Measured 2026-07-28, it does not:

      * cqr   0.7880 -> 0.8195 (width 98.9 -> 136.2)
      * split 0.8165 -> 0.8305 (width 102.3 -> 151.4)

    So de-levelling recovers roughly a third of the cqr gap and pays about 38 percent
    more width for it, but both stay under the 0.85 floor. The pin therefore stands
    unchanged, and this test records the partial result next to it so the limitation
    is not overstated as untouched, nor the fix overstated as complete. Rolling
    recalibration remains the effective response (see the gate above it).
    """
    train = _guarded_prices(_TRAIN_WINDOW)
    winter = _guarded_prices(_WINTER_WINDOW)

    covs = {}
    for tag, kw in (("raw", {}), ("normalized", _NORMALIZED)):
        f = PriceForecaster(confidence_level=0.9, method="cqr", **_SEED, **kw).fit(train)
        fc = f.predict_interval(winter)
        realized = winter.loc[fc.point.index]
        covs[tag] = float(((realized >= fc.lower) & (realized <= fc.upper)).mean())

    print(f"\nR2.1e out-of-season (cqr): raw={covs['raw']:.4f} normalized={covs['normalized']:.4f}")

    assert covs["normalized"] > covs["raw"], (
        "normalization no longer improves out-of-season coverage; the R2.1e finding "
        "that de-levelling recovers part of the season gap has regressed"
    )
    assert covs["normalized"] < _GATE_BAND[0], (
        f"normalized out-of-season coverage {covs['normalized']:.3f} now reaches the "
        f"gate band {_GATE_BAND} — the season limitation may be fixed; re-check the "
        "R2.1 claim and rewrite this test rather than relaxing it"
    )
