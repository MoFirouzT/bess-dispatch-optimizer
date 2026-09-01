"""Smoke test for `examples/quickstart.py`, the front-door script.

Separate from `test_examples_smoke.py` because that module skips whenever matplotlib
is absent, which is exactly the case in the base CI job. The quickstart is the one
script that must run on the **base install** (no token, no optional groups), so its
smoke has to execute where those groups are missing, or the claim in the README goes
untested precisely where it matters.

`DAYS` is shrunk: this asserts the script *runs*, not that its numbers are right (the
library gates own that).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "examples" / "quickstart.py"


@pytest.fixture
def quickstart(monkeypatch):
    """Import the script as a module, with the network token removed."""
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    spec = importlib.util.spec_from_file_location("quickstart", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_quickstart_runs_on_the_base_install(quickstart, monkeypatch, capsys):
    monkeypatch.setattr(quickstart, "DAYS", 3)
    quickstart.main()

    out = capsys.readouterr().out
    # Each of the four sections printed, so a silent early return cannot pass.
    for section in ("1. Dispatch", "2. Baselines", "3. Explanation", "4. Data trust"):
        assert section in out
