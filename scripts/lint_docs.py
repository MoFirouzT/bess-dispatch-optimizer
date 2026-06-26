#!/usr/bin/env python3
"""Documentation linter — the enforceable subset of the writing charter.

The full charter lives in ``docs/conventions.md`` §7; this script gates the
four rules that can be checked mechanically. Everything else there is review
judgment.

Checks (charter rule in parentheses):
  - no Markdown line stacks two or more em dashes        (rule 8)
  - every file stays under the line cap                  (rule 9)
  - no career / interview / positioning words anywhere   (rule 11)
  - canonical Tier-1/2 docs carry an ``*Assumes:*`` line (rule 5)

Scope: committed Markdown under ``docs/`` plus ``README.md``. ``STATE.md``
(a session work log) and the spec template are exempt from the prose checks
but still checked for forbidden words and length.

A line may suppress the per-line checks (em dashes, forbidden words) with a
trailing ``<!-- lint-ok -->`` HTML comment — invisible when rendered. Use it
sparingly; it does not affect the length or ``*Assumes:*`` checks.

Run:  uv run python scripts/lint_docs.py
Exits non-zero on any violation, printing ``path:line: message``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_LINES = 600
EM_DASH = "—"

# All committed Markdown in scope.
ALL_DOCS = sorted((ROOT / "docs").glob("**/*.md")) + [ROOT / "README.md"]

# Exempt from the *prose* checks (em dashes): work log + skeleton, not reader docs.
PROSE_EXEMPT = {ROOT / "docs" / "STATE.md", ROOT / "docs" / "specs" / "_TEMPLATE.md"}

# Canonical Tier-1/2 docs that must declare their assumed reader (rule 5).
CANONICAL = [
    "docs/formulation.md",
    "docs/architecture.md",
    "docs/conventions.md",
    "docs/glossary.md",
    "docs/market_reference.md",
    "docs/references.md",
]

# Unambiguous career/positioning words (rule 11). "resume" is intentionally
# omitted — it collides with the verb ("resume the solve") — and left to review.
FORBIDDEN = re.compile(
    r"\b(interview|interviews|interviewer|interviewing|hiring|recruiter|recruiting|anti-candidate)\b",
    re.IGNORECASE,
)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> int:
    errors: list[str] = []

    for path in ALL_DOCS:
        lines = path.read_text(encoding="utf-8").splitlines()

        # rule 9 — line cap (every doc)
        if len(lines) > MAX_LINES:
            errors.append(
                f"{rel(path)}: {len(lines)} lines over the {MAX_LINES}-line cap (rule 9) — split it"
            )

        for n, line in enumerate(lines, 1):
            # Inline escape hatch for the per-line checks; use sparingly, e.g. a
            # line that must quote a banned word or show the em-dash format.
            if "<!-- lint-ok" in line:
                continue

            # rule 11 — no career/positioning words (every doc)
            for match in FORBIDDEN.finditer(line):
                errors.append(
                    f"{rel(path)}:{n}: forbidden word {match.group(0)!r} "
                    "(rule 11) — strategy stays Tier 0"
                )

            # rule 8 — at most one em dash per line (reader docs only)
            if path not in PROSE_EXEMPT and line.count(EM_DASH) >= 2:
                errors.append(
                    f"{rel(path)}:{n}: {line.count(EM_DASH)} em dashes on one line (rule 8) "
                    "— keep at most one; use a colon, period, or parentheses"
                )

    # rule 5 — canonical docs declare their assumed reader
    for name in CANONICAL:
        path = ROOT / name
        if not path.exists():
            errors.append(f"{name}: canonical doc missing")
        elif "*Assumes:" not in path.read_text(encoding="utf-8"):
            errors.append(f"{name}: no `*Assumes:*` reader line (rule 5)")

    if errors:
        print("Doc lint: FAIL")
        for e in errors:
            print(f"  - {e}")
        print(f"\n{len(errors)} issue(s). See docs/conventions.md §7.")
        return 1

    print(f"Doc lint: OK — {len(ALL_DOCS)} files, charter rules 5/8/9/11 clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
