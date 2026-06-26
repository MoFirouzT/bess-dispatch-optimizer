"""Golden — ENTSO-E A44 parser maps raw XML to the internal price-series schema.

Contract: docs/specs/R1.4b-entsoe-loader.md § "Golden / property expectations".

No real ENTSO-E data is committed (licensing — see the spec). This XML is
**synthetic**: fabricated prices encoding the real *structure* the parser must
handle — 1-based positions, `PT60M`, UTC `timeInterval`, an `A03` curve with a
missing position (carry-forward gap). The parse_prices A03 expansion (entsoe-py)
forward-fills the missing position with the previous price.
"""

import pandas as pd

from bess.data.entsoe import parse_day_ahead_xml

# One TimeSeries, one hourly Period spanning four slots (22:00..01:00 UTC).
# Positions 1, 2, 4 are present; position 3 is omitted → carries 9.0 forward.
SYNTHETIC_A44_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0">
  <TimeSeries>
    <mRID>1</mRID>
    <curveType>A03</curveType>
    <currency_Unit.name>EUR</currency_Unit.name>
    <price_Measure_Unit.name>MWH</price_Measure_Unit.name>
    <Period>
      <timeInterval>
        <start>2024-06-30T22:00Z</start>
        <end>2024-07-01T02:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>10.5</price.amount></Point>
      <Point><position>2</position><price.amount>9.0</price.amount></Point>
      <Point><position>4</position><price.amount>12.0</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>"""


def test_parse_day_ahead_xml_golden():
    s = parse_day_ahead_xml(SYNTHETIC_A44_XML)

    # Internal schema: named, tz-aware UTC, hourly, gap-free.
    assert s.name == "price_eur_mwh"
    assert str(s.index.tz) == "UTC"
    assert len(s) == 4
    assert (s.index.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()

    expected = pd.Series(
        [10.5, 9.0, 9.0, 12.0],  # position 3 absent → 9.0 carried forward
        index=pd.to_datetime(
            [
                "2024-06-30T22:00Z",
                "2024-06-30T23:00Z",
                "2024-07-01T00:00Z",  # carried-forward gap
                "2024-07-01T01:00Z",
            ]
        ).tz_convert("UTC"),
        name="price_eur_mwh",
    )
    pd.testing.assert_series_equal(s, expected, check_freq=False)
