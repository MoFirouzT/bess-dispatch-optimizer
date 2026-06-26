"""Fixture price loader — reads a committed parquet slice into the internal
price-series schema the backtest consumes.

Spec: ``docs/specs/R1.4a-backtest.md`` § "Data". The internal contract is a
``pandas.Series`` named ``price_eur_mwh`` on a tz-aware **UTC** ``DatetimeIndex``
with a regular frequency and no gaps (conventions §1/§4). Raw ENTSO-E shapes are
*not* handled here — that adapter is R1.4b; this only loads the validated fixture.

``data`` is a leaf package: it imports nothing else in ``bess`` (import-linter).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PRICE_COL = "price_eur_mwh"


def validate_price_series(s: pd.Series, *, source: str = "price series") -> pd.Series:
    """Validate the internal price-series schema; return the series unchanged.

    The schema (conventions §1/§4): a tz-aware **UTC** ``DatetimeIndex``, sorted
    ascending, with a single regular frequency and no gaps. Raises ``ValueError``
    naming ``source`` on any violation. Shared by the fixture loader and the
    ENTSO-E adapter (``bess.data.entsoe``) so both enforce one contract.
    """
    idx = s.index
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
