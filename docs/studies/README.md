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
| [Stochastic value](stochastic-value.md) | Does hedging across scenarios beat optimizing against the mean forecast? | **Yes.** Median +12 EUR per window, positive on 62% of 63 real days |
| [Forecast value](forecast-value.md) | Does a better price forecast earn more euros? | **Null.** Distribution centred on zero despite clear statistical skill |
| [Tail value](tail-value.md) | Does pricing unprecedented spikes in the scenarios earn more euros? | **Null** at every recourse budget |
| [Bid curves](bid-curves.md) | Does a price-contingent commitment beat a single blind schedule? | **Null**, but it surfaced an unpriced delivery gap |
| [Target normalization](target-normalization.md) | Does de-levelling the forecast target improve the forecaster? | **Null** at the shipped window; a real gain at two years |
| [Storage duration](storage-duration.md) | How much does the economics depend on the energy-to-power ratio? | Strongly. The annualized ceiling falls by roughly a quarter from 1 h to 4 h |
| [Solve scaling](solve-scaling.md) | Does the program stay tractable as the horizon and scenario count grow? | Yes on both axes, at very different rates |

## Why the nulls are here rather than hidden

Four of the seven came back null, and three of those share one mechanism:
**intraday recourse adjusts after the price is known**, so a better *representation*
of the day-ahead future has little left to buy. That is a result about this market
and this asset, not a failure of the implementation, and each page says how it was
distinguished from one.

The distinction is load-bearing, so each null is held to the same standard as a
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

Every euro figure comes from real ENTSO-E Dutch day-ahead prices fetched at
runtime; no market data is committed. Reproduction commands need a token
(`.env.example`), and each page names the window it ran on.

The standing limitation across the value studies: they rest on a single 2024
window. That is the same single-window criticism the forecaster's own evaluation
harness fixed for itself, one level up, and re-windowing them is open work.
