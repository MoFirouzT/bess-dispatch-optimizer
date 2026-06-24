"""CI smoke test: the HiGHS backend is installed and Pyomo can solve with it.

Infrastructure sanity only — **not** a formulation gate. The correctness gates
are the golden oracles (tests/golden) and property tests (tests/property),
written against docs/formulation.md.
"""

import pytest
from pyomo.environ import (
    ConcreteModel,
    Constraint,
    Objective,
    SolverFactory,
    Var,
    maximize,
    value,
)


def test_appsi_highs_available_and_solves():
    solver = SolverFactory("appsi_highs")
    assert solver.available(), "appsi_highs (HiGHS) must be installed for the optimizer"

    m = ConcreteModel()
    m.x = Var(bounds=(0, 1))
    m.cap = Constraint(expr=m.x <= 0.5)
    m.obj = Objective(expr=2 * m.x, sense=maximize)
    solver.solve(m)

    assert value(m.x) == pytest.approx(0.5, abs=1e-6)
    assert value(m.obj) == pytest.approx(1.0, abs=1e-6)
