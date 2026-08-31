"""Fixture price loader — reads a committed parquet slice into the internal
price-series schema the backtest consumes.

Spec: ``docs/specs/backtest.md`` § "Data". The internal contract is a
``pandas.Series`` named ``price_eur_mwh`` on a tz-aware **UTC** ``DatetimeIndex``
with a regular frequency and no gaps (conventions §1/§4). Raw ENTSO-E shapes are
*not* handled here — that adapter is R1.4b; this only loads the validated fixture.

``data`` is a leaf package: it imports nothing else in ``bess`` (import-linter).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PRICE_COL = "price_eur_mwh"


def synthetic_day_ahead(days: int = 90, seed: int = 42, spread_scale: float = 1.0) -> pd.Series:
    """Deterministic, copyright-clean NL-like hourly day-ahead series.

    A single dominant daily cycle (cheap nights, morning ramp, evening peak) with
    day-to-day level noise and an occasional solar-driven midday dip. Shaped like a
    calm month of Dutch day-ahead prices but **synthetic** — no real or third-party
    market data is committed (conventions / the no-committed-data rule). Used by the
    structural sanity gate (``tests/golden/test_sanity_band.py``) and the worked
    example (``examples/worked_example.py``) so both share one source.

    ``spread_scale`` stretches the daily cycle about its own mean, widening the
    peak-to-trough spread without shifting the price level: ``2.0`` is a volatile
    month, the default ``1.0`` the calm one. It lets the band gate run across
    volatility regimes token-free (a *real* volatile slice cannot be committed;
    see docs/decisions/no-committed-market-data.md). At the default the arithmetic is untouched, so
    the series is
    bit-identical to before the parameter existed.
    """
    rng = np.random.default_rng(seed)
    shape = np.array(
        [32, 30, 29, 28, 28, 30, 34, 40, 46, 50, 52, 50,
         47, 45, 46, 50, 57, 66, 78, 90, 94, 84, 64, 44],
        dtype=float,
    )  # fmt: skip
    if spread_scale != 1.0:
        shape = shape.mean() + (shape - shape.mean()) * spread_scale
    idx = pd.date_range("2024-01-01", periods=days * 24, freq="1h", tz="UTC")
    out = []
    for _ in range(days):
        p = shape + rng.normal(0, 11) + rng.normal(0, 4, 24)
        if rng.random() < 0.10:  # occasional solar-driven midday dip
            p[11:15] -= rng.uniform(25, 45)
        out.append(p)
    return pd.Series(np.concatenate(out), index=idx, name=PRICE_COL)


#: The drift regimes R2.1g selects its knobs on. Named rather than free-form because
#: the selection is only reproducible if the instrument is fixed: a half-life chosen
#: against an ad-hoc series is a number nobody can re-derive.
DRIFT_REGIMES = ("calm", "ramp", "changepoint", "volatility")


def synthetic_drift(
    *,
    regime: str = "calm",
    days: int = 560,
    seed: int = 11,
    strength: float = 1.0,
    at: float = 0.5,
) -> pd.Series:
    """A synthetic day-ahead series carrying a named, reproducible drift regime.

    R2.1g selects its two knobs (the weight half-life and the ACI step size) on
    simulated drift rather than on real prices, because both are functions of a drift
    rate that can be simulated with a known answer, and because an online method
    traverses the whole span so there is no clean held-out block to select on
    (spec ``drift-robust-conformal.md``, Decisions). That only works if the instrument
    is fixed and seeded, which is what this is.

    The regimes, each a transformation of :func:`synthetic_day_ahead` so the daily
    shape and noise are held constant and only the drift differs:

    - ``"calm"``: unchanged. The control. Exchangeability roughly holds, so a knob that
      costs width here is a knob that costs width for nothing.
    - ``"ramp"``: a multiplicative level climb to ``1 + strength`` times the start, the
      2021 crisis shape. Coverage decays gradually and never recovers.
    - ``"changepoint"``: a single multiplicative step at fraction ``at`` of the span.
      The case Barber et al.'s ``rho ** k`` corollary is stated for, so the measured
      coverage can be read against a bound rather than only against the incumbent.
    - ``"volatility"``: the level holds and the daily spread scales to
      ``1 + strength``, drift in the second moment only. The case that separates the
      two arms: it moves the scores without moving the level, so weighting should help
      and a level correction should not.

    ``strength`` is the size of the move (``1.0`` doubles the level or the spread) and
    ``at`` is where a changepoint falls. Both are explicit because the *shape* of the
    drift is what the knobs are being fitted to, so it belongs in the call, not in a
    magic constant.
    """
    if regime not in DRIFT_REGIMES:
        raise ValueError(f"regime must be one of {DRIFT_REGIMES}; got {regime!r}")
    if strength < 0.0:
        raise ValueError(f"strength must be >= 0; got {strength}")
    if not 0.0 < at < 1.0:
        raise ValueError(f"at must be in (0, 1); got {at}")

    base = synthetic_day_ahead(days=days, seed=seed)
    n = len(base)
    values = base.to_numpy(dtype=float)

    if regime == "calm":
        out = values
    elif regime == "ramp":
        out = values * (1.0 + strength * np.linspace(0.0, 1.0, n))
    elif regime == "changepoint":
        step = np.where(np.arange(n) >= int(n * at), 1.0 + strength, 1.0)
        out = values * step
    else:  # volatility: scale the deviation from each day's own mean, level held
        daily = values.reshape(days, 24)
        level = daily.mean(axis=1, keepdims=True)
        ramp = 1.0 + strength * np.linspace(0.0, 1.0, days).reshape(days, 1)
        out = (level + (daily - level) * ramp).reshape(-1)

    return pd.Series(out, index=base.index, name=PRICE_COL)


def validate_utc_index(idx: pd.Index, *, source: str = "series") -> None:
    """Validate the internal time-index schema; raise ``ValueError`` on violation.

    The schema (conventions §1/§4): a tz-aware **UTC** ``DatetimeIndex``, sorted
    ascending, with a single regular frequency and no gaps. Shared by the price
    fixture loader, the ENTSO-E price adapter, and the R2.1c fundamentals loader
    so every internal time series enforces one index contract.
    """
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError(f"{source}: index must be a DatetimeIndex, got {type(idx).__name__}")
    if idx.tz is None or str(idx.tz) != "UTC":
        raise ValueError(f"{source}: index must be tz-aware UTC, got tz={idx.tz}")
    if not idx.is_monotonic_increasing:
        raise ValueError(f"{source}: index must be sorted ascending")

    # A regular, gap-free series: every step equals the modal step.
    if len(idx) >= 2:
        steps = idx.to_series().diff().dropna()
        if steps.nunique() != 1:
            raise ValueError(
                f"{source}: gaps / irregular freq — steps seen: "
                f"{sorted(set(steps))} (expected a single regular frequency)"
            )


def validate_price_series(s: pd.Series, *, source: str = "price series") -> pd.Series:
    """Validate the internal price-series schema; return the series unchanged.

    Thin wrapper over ``validate_utc_index`` (the shared index contract); kept as
    the price-specific entry point the fixture loader and ENTSO-E price adapter call.
    """
    validate_utc_index(s.index, source=source)
    return s


def load_prices(path: str | Path) -> pd.Series:
    """Load and validate a committed price fixture; return the ``price_eur_mwh`` Series.

    Raises ``ValueError`` if the schema is violated (missing column, tz-naive or
    non-UTC index, unordered index, or a gap in an otherwise regular series).
    """
    df = pd.read_parquet(path)
    if PRICE_COL not in df.columns:
        raise ValueError(f"fixture {path} is missing the {PRICE_COL!r} column")

    s = df[PRICE_COL].astype(float)
    s.name = PRICE_COL
    return validate_price_series(s, source=f"fixture {path}")
