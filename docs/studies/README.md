# Studies

Questions asked *about* the dispatch stack, each answered with a measurement and
reported here as a finding. None of this code is on the serving path: it lives in
`src/bess/studies/`, outside the import chain, and an import-linter contract
forbids the serving layers from reaching into it.

*Assumes:*
the capability map in [architecture.md](../architecture.md);
the evaluation semantics in [formulation-evaluation.md](../formulation-evaluation.md) § R2.5;
each page names the spec that governs its method.

---

## Findings

| Study | Question | Answer |
| --- | --- | --- |
| [Stochastic value](stochastic-value.md) | Does hedging across scenarios beat optimizing against the mean forecast? | **Yes on BE** (+8.36 EUR per window, interval above zero); **directionally yes on NL** (+5.76, interval includes zero) |
| [Forecast value](forecast-value.md) | Does a better price forecast earn more euros? | **Null** in both markets, despite clear statistical skill |
| [Tail value](tail-value.md) | Does pricing unprecedented spikes in the scenarios earn more euros? | **Null** at every recourse budget and in every year |
| [Bid curves](bid-curves.md) | Does a price-contingent commitment beat a single blind schedule? | **Null**, but it surfaced an unpriced delivery gap that the wider window confirmed |
| [Target normalization](target-normalization.md) | Does de-levelling the forecast target improve the forecaster? | **Yes**, and it flips which training window is best |
| [Storage duration](storage-duration.md) | How much does the economics depend on the energy-to-power ratio? | Strongly. The annualized ceiling falls by roughly a quarter from 1 h to 4 h |
| [Interval sharpness](interval-sharpness.md) | Can the forecaster's intervals be made narrower without losing calibration? | **Yes but not adoptably**: 4.5% narrower on NL, rejected because the narrowing pushes 11:00 into undercoverage |
| [Drift-robust conformal](drift-robust-conformal.md) | Which repair keeps the intervals calibrated through a regime shift? | **Null** at a monthly refit: at most +0.019 worst-year coverage against a +0.03 bar. Refitting monthly rather than annually is worth +0.18 and a 35% narrower interval, so the decay was mostly model staleness, not calibration staleness |
| [Solve scaling](solve-scaling.md) | Does the program stay tractable as the horizon and scenario count grow? | Yes on both axes, at very different rates |

## Why the nulls are here rather than hidden

Four of the nine came back null. Three of them share one mechanism:
**intraday recourse adjusts after the price is known**, so a better *representation*
of the day-ahead future has little left to improve. That is a result about this market
and this asset, not a failure of the implementation, and each page says how it was
distinguished from one. The fourth, drift-robust conformal, is null for an unrelated
reason: the coverage decay it set out to repair turned out to be mostly model staleness,
which a refit schedule fixes and a calibration construction cannot.

Each null is therefore held to the same standard as a
positive result. The three euro-comparison studies (forecast, tail, bid curve) each
carry a golden oracle pinning the scoring arithmetic and a property test pinning
degeneracy: comparing a thing against itself must return exactly zero. The forecast
and tail studies additionally gate **antisymmetry**, that swapping the two inputs
flips the sign; the bid-curve study cannot, because it compares two commitments
fitted on the same training set rather than two interchangeable sets.

Each of the three is also measured on a **designed instance where the effect is
real**, and detects it there. That is what separates a null from a silently broken
comparison, and in the tail study it caught an actual defect in the measurement
before the result was believed.

**No result on these pages is sign-asserted.** The gates check that a number is
computed correctly, never that it came out favourable.

## Provenance

Every euro figure comes from real ENTSO-E Dutch and Belgian day-ahead prices fetched
at runtime; no market data is committed. Reproduction commands need a token
(`.env.example`), and each page names the window it ran on. The full re-measurement is
its own deliberate run, `uv run pytest -m "integration and studies" -s`, kept out of
the routine live tier because it takes about an hour.

The four euro studies are measured on **260 delivery days in 52 blocks spread over
2022-01-01 to 2025-09-29**, the same layout the price forecaster is evaluated on, with
the two headline studies repeated on BE. Each quoted interval resamples whole blocks
rather than individual windows, because consecutive days share almost all of their
training history.

They previously rested on a single 2024 quarter; [R2.7](../specs/study-windowing.md)
re-measured them and each page records what moved. The short version: **the three nulls
held and hardened, and the one positive result got smaller.**

Every euro figure here carries **two independent widths**, both now measured. Window
sampling is the quoted interval. **Scenario-draw noise** is the second: the 30-path
bootstrap is itself random, so the same protocol on the same days under a different seed
gives a different answer. [R2.8](../specs/draw-noise.md) measured it at 4.85 EUR for
stochastic value and 11.19 for forecast value, roughly a third of each study's window
interval. The two are never combined, and the draw spread is not a confidence interval:
it says how far a rerun moves, not how uncertain the market is.

The headline for those two studies is therefore the **mean across seeds**, with the
default-seed value named on each page so the published command still reproduces a stated
number. Tail value and bid curves keep single-seed figures, since a mean across seeds of
medians that are all exactly zero is zero.

**The draw moves magnitudes, not signs.** Across seeds the share of windows above zero
varies by 5 or 6 points while the medians move by factors of 2.5 and 33. Every finding on
this page keeps its direction under reseeding.
