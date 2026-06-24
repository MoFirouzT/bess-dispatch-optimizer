"""bess — BESS day-ahead dispatch optimizer.

Layered package; the dependency direction is enforced by import-linter
(see pyproject ``[tool.importlinter]``):

    api → explain → stochastic → recourse → optimizer → assets

with ``forecaster`` / ``scenarios`` feeding ``stochastic``. ``optimizer`` must
never import ``api``. The math lives in ``docs/formulation.md`` (single source
of truth); each layer is built one phase at a time (see ``docs/STATE.md``).
"""
