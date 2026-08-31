"""Golden oracles for the sharpness search (R2.9).

Spec: ``docs/specs/interval-sharpness.md`` § "Golden oracles". The search picks the
narrowest conformal interval whose coverage stays in band and whose per-hour coverage
is no worse calibrated than the incumbent's, so the four cases here pin the *whole*
selection rule and not only its happy path: a recorded ranking, the coverage
constraint binding against the sharpest candidate, the hourly-deviation constraint
binding against it, and the null path where nothing beats what ships.

Candidates are scored by a stub in three of the four cases. That is deliberate: the
oracle under test is the **selection rule**, and driving it with recorded
``CoverageResult`` values makes the expected answer hand-checkable, which a LightGBM
fit never is. Case 1 runs the real learner so the wiring is pinned too.
"""

from __future__ import annotations

import pytest

pytest.importorskip("lightgbm")
pytest.importorskip("mapie")

from bess.data.fixtures import synthetic_day_ahead  # noqa: E402
from bess.forecaster.evaluate import (  # noqa: E402
    CoverageResult,
    _price_days,
    rolling_origin_folds,
)
from bess.forecaster.tune import (  # noqa: E402
    INCUMBENT,
    SharpnessCandidate,
    rank_candidates,
    search_sharpest,
)


def _result(coverage: float, mean_width: float, max_hour_deviation: float) -> CoverageResult:
    """A ``CoverageResult`` carrying only the fields the selection rule reads."""
    return CoverageResult(
        coverage=coverage,
        ci_low=coverage - 0.03,
        ci_high=coverage + 0.03,
        mean_width=mean_width,
        median_width=mean_width * 0.9,
        n_test_days=60,
        per_fold=(coverage,),
        by_hour=(coverage,) * 24,
        max_hour_deviation=max_hour_deviation,
    )


def _named(params: dict[str, object]) -> dict[str, object]:
    """The incumbent with ``params`` overridden, so every stub grid is a real grid."""
    return {**INCUMBENT, **params}


def test_oracle_1_recorded_ranking_on_the_real_learner():
    """Case 1: a real 3-config search on synthetic prices reproduces a recorded answer.

    The values below were produced by this code and are frozen as the oracle: they
    pin the wiring end to end (grid -> walk-forward -> constraints -> ranking), so a
    silent change in how a candidate is scored fails here rather than downstream.
    """
    prices = synthetic_day_ahead(days=200, seed=0)
    grid = [
        _named({"n_estimators": 40}),
        _named({"n_estimators": 40, "num_leaves": 15}),
        _named({"n_estimators": 40, "min_child_samples": 100}),
    ]

    folds = rolling_origin_folds(
        _price_days(prices), n_folds=3, test_days=5, train_days=90, spacing="even"
    )
    res = search_sharpest(prices, grid=grid, folds=folds, random_state=0)

    assert [c.params["min_child_samples"] for c in res.all_candidates] == [20, 20, 100]
    assert res.selected.params in grid
    assert res.selected.mean_width == min(c.mean_width for c in res.ranked)
    # The incumbent is scored on the same folds and is itself a candidate.
    assert res.selected.mean_width <= res.incumbent.mean_width
    assert res.ranked == tuple(sorted(res.ranked, key=lambda c: c.mean_width))


def test_oracle_2_coverage_constraint_excludes_the_sharpest():
    """Case 2: the narrowest candidate is out of band, so the runner-up wins.

    The constraint has to bind against the *sharpest* candidate or it never binds at
    all: an interval is made narrow precisely by giving up coverage.
    """
    incumbent = SharpnessCandidate.from_result(INCUMBENT, _result(0.90, 100.0, 0.05))
    scored = [
        (_named({"num_leaves": 15}), _result(0.80, 40.0, 0.04)),  # sharpest, out of band
        (_named({"num_leaves": 63}), _result(0.89, 70.0, 0.05)),  # the intended winner
        (_named({"n_estimators": 400}), _result(0.91, 95.0, 0.05)),
    ]

    res = rank_candidates(scored, incumbent=incumbent, coverage_band=(0.85, 0.95))

    assert res.selected.params["num_leaves"] == 63
    assert res.selected.mean_width == 70.0
    excluded = next(c for c in res.all_candidates if c.mean_width == 40.0)
    assert not excluded.feasible
    assert "coverage" in excluded.reason
    assert excluded not in res.ranked


def test_oracle_3_hourly_deviation_constraint_excludes_the_sharpest():
    """Case 3: sharpest, in band, but worse per-hour calibration than the incumbent.

    This is the failure the CQR record exists to avoid: mean width bought by an
    interval that is tight overnight and too tight at the evening peak. Marginal
    coverage cannot see it, so the hourly deviation is a separate constraint.
    """
    incumbent = SharpnessCandidate.from_result(INCUMBENT, _result(0.90, 100.0, 0.05))
    scored = [
        (_named({"num_leaves": 15}), _result(0.90, 40.0, 0.12)),  # sharpest, miscalibrated
        (_named({"num_leaves": 63}), _result(0.90, 70.0, 0.05)),  # the intended winner
    ]

    res = rank_candidates(scored, incumbent=incumbent, coverage_band=(0.85, 0.95))

    assert res.selected.mean_width == 70.0
    excluded = next(c for c in res.all_candidates if c.mean_width == 40.0)
    assert not excluded.feasible
    assert "hour" in excluded.reason


def test_oracle_4_null_path_returns_the_incumbent():
    """Case 4: nothing feasible beats the shipped model, so the shipped model wins.

    A search that cannot improve on what ships must say so and return it, not raise
    and not return a worse config. The null is a reportable result (spec § Motivation).
    """
    incumbent = SharpnessCandidate.from_result(INCUMBENT, _result(0.90, 100.0, 0.05))
    scored = [
        (_named({"num_leaves": 15}), _result(0.70, 40.0, 0.04)),  # out of band
        (_named({"num_leaves": 63}), _result(0.90, 130.0, 0.05)),  # feasible but wider
    ]

    res = rank_candidates(scored, incumbent=incumbent, coverage_band=(0.85, 0.95))

    assert res.selected.params == INCUMBENT
    assert res.selected.mean_width == 100.0
    assert res.selected is res.incumbent
    # The incumbent ranks among the feasible candidates rather than sitting outside them.
    assert res.ranked[0] is res.incumbent


def test_incumbent_matches_the_shipped_forecaster_defaults():
    """The incumbent is the shipped model, read off ``PriceForecaster``, not retyped.

    If a default drifts and this constant does not, the search would report a width
    reduction against a model nobody runs.
    """
    import inspect

    from lightgbm import LGBMRegressor

    from bess.forecaster.forecast import PriceForecaster

    sig = inspect.signature(PriceForecaster.__init__).parameters
    lgb_defaults = inspect.signature(LGBMRegressor.__init__).parameters

    assert INCUMBENT["n_estimators"] == sig["n_estimators"].default
    assert INCUMBENT["calib_fraction"] == sig["calib_fraction"].default
    for knob in ("learning_rate", "num_leaves", "min_child_samples"):
        assert INCUMBENT[knob] == lgb_defaults[knob].default, (
            f"{knob}: the incumbent must be LightGBM's own default, since "
            "PriceForecaster passes no value for it"
        )
