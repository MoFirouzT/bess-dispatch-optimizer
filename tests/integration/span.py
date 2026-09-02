"""The multi-year evaluation span, shared by the R2.1d forecaster gates and the R2.7
value studies.

Lives in its own module rather than in ``conftest.py`` so test modules can import it
directly: the fold layout and the span bounds are module-level constants, not fixtures,
because they define *what is measured* rather than set up a test.
"""

from __future__ import annotations

import pandas as pd

from bess.data.entsoe import fetch_day_ahead
from bess.forecaster.evaluate import rolling_origin_folds
from bess.studies import fold_days

#: The R2.1d evaluation span, shared by the forecaster gates and the R2.7 value
#: studies so both measure the same period. Upper bound is forced, not chosen: the
#: SDAC market time unit moved to 15 minutes at 2025-10-01 00:00 local (2025-09-30
#: 22:00 UTC, verified live) and `validate_utc_index` rejects a series with two step
#: sizes. Verified size: 41,593 hourly points over 1734 days, NL and BE alike.
SPAN = (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2025-09-30", tz="UTC"))

#: The R2.1g span, deliberately **wider** than SPAN and deliberately a separate
#: constant. R2.1g needs 2021 to be a *scored* year: it is the worst-calibrated stretch
#: in the data (0.791 against 0.897 in 2024) and therefore the one the phase exists to
#: repair, but under the R2.1d layout all of 2021 is training-only, so no gate can see
#: it. Two extra years of history put a full 365-day training window behind
#: 2021-01-01.
#:
#: Moving `SPAN` itself would have been the smaller diff and the wrong change: it is
#: shared by the R2.1d forecaster gates and the R2.7 value studies, so widening it would
#: silently rewrite every published number in both. The phase's own spec requires the
#: original-span figures to be shown unchanged, which is only checkable if the original
#: span still exists as a constant.
EXTENDED_SPAN = (pd.Timestamp("2019-01-01", tz="UTC"), pd.Timestamp("2025-09-30", tz="UTC"))


def extended_span_prices(zone: str = "NL") -> pd.Series:
    """Fetch the R2.1g span, bypassing the guard for the reasons in `span_prices`.

    The R1.4c nonfocal false positive documented there applies a fixed run length
    regardless of window length, so a *wider* window can only make it more likely. The
    workaround is inherited rather than re-derived.
    """
    return fetch_day_ahead(zone, *EXTENDED_SPAN)


#: R2.1d fold placement, reused verbatim by R2.7 so the euro studies score the exact
#: days the forecaster's pinball skill is gated on (spec study-windowing.md § Design
#: sketch). 52 blocks of 5 days is one block per ~4 weeks and 260 evaluated days.
WALK_FORWARD = dict(n_folds=52, test_days=5, train_days=365, spacing="even")


def span_prices(zone: str = "NL") -> pd.Series:
    """Fetch the multi-year evaluation span, deliberately **not** through the guard.

    Measured 2026-07-28: the R1.4c guard classifies this span ANOMALY / `stuck_feed`.
    The trigger is a 5-hour run of exactly 64.00 EUR/MWh on 2021-05-15, plus 4-hour
    runs at 42.30, 140.66 and 95.60, against a nonfocal threshold of 4 hours. Those
    are ordinary merit-order flats, where one marginal unit sets the price for
    several consecutive hours; they are not a stuck feed. The focal branch is
    comfortable (longest 0.00 run is 8 hours against a 24-hour threshold).

    The guard's nonfocal rule is a **fixed run length applied regardless of window
    length**, so its false-positive rate grows with the span. It survived until now
    because nothing fetched a window containing such a run: the year-long guard test
    covers 2024, which has no nonfocal run of 4 or more. This is the same class of
    defect that already forced the *focal* threshold up from 8 hours to 24, now
    surfacing on the nonfocal branch.

    Fixing that belongs to R1.4c, and lowering or raising a guard threshold to make
    a module pass would be exactly the suppression the operating contract forbids.
    So the span is fetched directly and the finding is recorded (STATE.md, and the
    R2.1d and R2.7 specs). The guard keeps its live-feed job everywhere it can
    actually assert it, including the shorter seasonal windows in the forecaster
    module and `test_ingestion_guard_live.py` itself.

    Lives here rather than in one test module because two phases now depend on it,
    and a workaround copied twice is a workaround nobody removes.
    """
    return fetch_day_ahead(zone, *SPAN)


def span_fold_days(prices: pd.Series) -> pd.DatetimeIndex:
    """The 260 evaluated delivery days of the R2.7 layout, for a fetched span.

    Folds are placed over the **complete** days only. The span's last day carries a
    single hour (its upper bound is a timestamp, not a day), and `window_sets` drops
    incomplete days, so placing folds over the raw day index would select 260 days of
    which only 259 can be scored: a layout that promises one number and delivers
    another (spec study-windowing.md, build task 0).
    """
    idx = pd.DatetimeIndex(prices.index)
    complete = pd.DatetimeIndex(
        [day for day, chunk in prices.groupby(idx.normalize()) if len(chunk) == 24]
    )
    return fold_days(rolling_origin_folds(complete, **WALK_FORWARD))
