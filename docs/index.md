# Documentation

The written record for the dispatch optimizer: the math it implements, the conventions
that math is written in, what the stack was measured to be worth, and the reasoning
behind each non-obvious choice.

*Assumes:*
nothing yet. Start at [Architecture](architecture.md) for the map, or
[Results](results.md) for the numbers. Terms are defined in the
[glossary](glossary.md).

---

## Where to start

**To understand what the system does**, read [Architecture](architecture.md). It maps
the capabilities to the code's packages and gives the order to read the rest in.

**To check a number**, read [Results](results.md). Every euro figure names the study
that produced it, and the [studies](studies/README.md) carry the method, the nulls
included.

**To check the math**, read [the formulation](formulation.md), starting at its
*Conventions* section, where the grid-side metering rule is stated. That rule is the
model: power is metered grid-side, so degradation is a cost subtracted from cash and
never an efficiency factor. Uncertainty and evaluation are in the two companion files.

**To understand why something is the way it is**, read the
[decisions](decisions/README.md). One file per non-obvious choice, each with the
alternatives that were rejected and the failure mode it guards against.

## About this site

These are the same Markdown files the repository serves on GitHub, which is the
primary rendering: they are written for its math dialect and its heading anchors. The
site adds an ordered nav and a search box over them. Nothing here is generated from
source, and there is no API reference built from docstrings, because the docs are the
argument and a listing of every module would bury it.

A few links point at files outside `docs/` (the README, the operating contract, the
example scripts). Those resolve in
[the repository](https://github.com/MoFirouzT/bess-dispatch-optimizer) rather than here.
