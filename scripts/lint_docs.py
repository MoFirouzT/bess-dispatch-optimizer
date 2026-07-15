#!/usr/bin/env python3
"""Documentation linter: the enforceable subset of the writing charter.

The full charter lives in ``docs/conventions.md`` §7; this script gates the
four rules that can be checked mechanically. Everything else there is review
judgment.

Checks (charter rule in parentheses):
  - no line contains an em dash                          (rule 8)
  - every file stays under the line cap                  (rule 9)
  - no career / interview / positioning words anywhere   (rule 11)
  - canonical Tier-1/2 docs carry an ``*Assumes:*`` line (rule 5)

Plus a set of checks that bind prose to reality. Docs rot silently because a
sentence about the code is not executable, so nothing fails when the code moves
underneath it. These make the checkable subset fail loudly instead:

  - math renders on GitHub: no LaTeX spacing control symbols, no ``$ x$``
  - a spec's ``bess.x.y`` references name real modules/attributes
  - ``Depends on:`` IDs name real specs, and the graph is acyclic
  - cross-doc ``file.md#anchor`` links resolve to a real heading
  - specs carry no instruction that was already carried out

Scope: committed Markdown under ``docs/`` plus ``README.md``. The em-dash ban
applies to every file, ``STATE.md`` (a session work log) and the spec template
included; those two stay exempt only from the ``*Assumes:*`` check.

A line may suppress the per-line checks (em dashes, forbidden words) with a
trailing ``<!-- lint-ok -->`` HTML comment, invisible when rendered. Use it
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

# Canonical Tier-1/2 docs that must declare what they take as given (rule 5).
CANONICAL = [
    "docs/formulation.md",
    "docs/architecture.md",
    "docs/conventions.md",
    "docs/glossary.md",
    "docs/market_reference.md",
    "docs/references.md",
]

# Unambiguous career/positioning words (rule 11). "resume" is intentionally
# omitted (it collides with the verb, "resume the solve") and left to review.
FORBIDDEN = re.compile(
    r"\b(interview|interviews|interviewer|interviewing|hiring|recruiter|recruiting|anti-candidate)\b",
    re.IGNORECASE,
)

SPECS = sorted((ROOT / "docs" / "specs").glob("*.md"))

# LaTeX spacing *control symbols*. GitHub's Markdown treats a backslash before ASCII
# punctuation as an escape and drops the backslash before MathJax runs, so `\,` and
# `\;` render as literal "," and ";" inside formulas. Control *words* (\quad, \Bigl)
# are unaffected. These are cosmetic, so the fix is to delete them.
MATH_SPACING = re.compile(r"\\[,;:!]")

# Inline math whose content starts or ends with a space: `$ x$`. GitHub may then
# refuse to parse the span as math at all.
INLINE_MATH = re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)")

# Instructions that were carried out long ago and then rotted in place. Every one of
# these was live in a spec while the thing it demanded already existed.
STALE_INTENT = re.compile(
    r"(to be recorded as ADRs|to record in `?docs/references\.md|when the module lands"
    r"|no `?formulation\.md`? text is written until|written into `?formulation\.md`? only after"
    r"|is written until .{0,20}approved)",
    re.IGNORECASE,
)

# A spec naming a module/function path that no longer exists (e.g. `bess.forecaster.model`).
CODE_REF = re.compile(r"`(bess\.[a-z_][a-z0-9_.]*)`")

# `**Depends on:** ...` phase IDs, e.g. R1.4a, R2.1b. Bare "R1.4" resolves to no spec.
DEPENDS_LINE = re.compile(r"\*\*Depends on:\*\*(.*)")
PHASE_ID = re.compile(r"\bR\d+\.\d+[a-z]?\b")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _spec_ids() -> set[str]:
    """Phase IDs that have a real spec file, e.g. {"R1.4a", "R2.3"}."""
    ids = set()
    for p in SPECS:
        m = re.match(r"(R\d+\.\d+[a-z]?)-", p.name)
        if m:
            ids.add(m.group(1))
    return ids


def _module_exists(dotted: str) -> bool:
    """Does `bess.a.b` name a real module, package, or an attribute defined in one?"""
    parts = dotted.split(".")
    for cut in range(len(parts), 1, -1):
        base = ROOT / "src" / Path(*parts[:cut])
        if base.with_suffix(".py").exists() or (base / "__init__.py").exists():
            if cut == len(parts):
                return True
            # Trailing parts should be defined in the module we found.
            src = (
                base.with_suffix(".py")
                if base.with_suffix(".py").exists()
                else base / "__init__.py"
            )
            text = src.read_text(encoding="utf-8")
            return all(re.search(rf"\b{re.escape(a)}\b", text) for a in parts[cut:])
    return False


def check_depends_graph(errors: list[str]) -> None:
    """Every `Depends on:` ID resolves to a real spec, and the graph is acyclic.

    Catches the R1.4c -> R1.5 cycle (a leftover from the R1.5b rename) and bare "R1.4",
    which names no spec at all (the phases are R1.4a/b/c).
    """
    known = _spec_ids()
    edges: dict[str, set[str]] = {}
    for path in SPECS:
        m = re.match(r"(R\d+\.\d+[a-z]?)-", path.name)
        if not m:
            continue  # _TEMPLATE.md
        owner = m.group(1)
        line = DEPENDS_LINE.search(path.read_text(encoding="utf-8"))
        if not line:
            continue
        deps = set()
        for dep in PHASE_ID.findall(line.group(1)):
            if dep == owner:
                continue
            if dep not in known:
                errors.append(
                    f"{rel(path)}: `Depends on:` names {dep}, which is not a spec "
                    f"(known: {', '.join(sorted(known))})"
                )
                continue
            deps.add(dep)
        edges[owner] = deps

    # Cycle detection over the declared graph.
    state: dict[str, int] = {}

    def visit(node: str, trail: list[str]) -> None:
        if state.get(node) == 1:
            cycle = " -> ".join(trail[trail.index(node) :] + [node])
            errors.append(f"docs/specs: `Depends on:` cycle {cycle}")
            return
        if state.get(node) == 2:
            return
        state[node] = 1
        for dep in sorted(edges.get(node, ())):
            visit(dep, [*trail, node])
        state[node] = 2

    for node in sorted(edges):
        visit(node, [])


def _gh_slug(heading: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation, each space -> one hyphen.

    Whitespace is *not* collapsed, so "a + b" slugs to "a--b" (the "+" is dropped,
    leaving two spaces, hence two hyphens). Collapsing here would wrongly flag those.
    """
    return re.sub(r"[^\w\s-]", "", heading.strip().lower()).replace(" ", "-")


def check_anchors(errors: list[str]) -> None:
    """Every cross-doc `file.md#anchor` link resolves to a real heading.

    Catches links left behind when a heading is reworded, which read as fine in the
    source and silently land at the top of the page.
    """
    headings: dict[Path, set[str]] = {}
    for path in ALL_DOCS:
        text = path.read_text(encoding="utf-8")
        headings[path] = {_gh_slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}

    link = re.compile(r"\]\(([^)\s#]*\.md)#([\w-]+)\)")
    for path in ALL_DOCS:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for target, anchor in link.findall(line):
                dest = (path.parent / target).resolve()
                if dest not in headings:
                    continue  # outside the doc set; the link check is not a file check
                if anchor not in headings[dest]:
                    errors.append(
                        f"{rel(path)}:{n}: link to `{target}#{anchor}` matches no heading there"
                    )


def main() -> int:
    errors: list[str] = []

    for path in ALL_DOCS:
        lines = path.read_text(encoding="utf-8").splitlines()

        # rule 9: line cap (every doc)
        if len(lines) > MAX_LINES:
            errors.append(
                f"{rel(path)}: {len(lines)} lines over the {MAX_LINES}-line cap (rule 9): split it"
            )

        for n, line in enumerate(lines, 1):
            # Inline escape hatch for the per-line checks; use sparingly, e.g. a
            # line that must quote a banned word.
            if "<!-- lint-ok" in line:
                continue

            # rule 11: no career/positioning words (every doc)
            for match in FORBIDDEN.finditer(line):
                errors.append(
                    f"{rel(path)}:{n}: forbidden word {match.group(0)!r} "
                    "(rule 11): strategy stays Tier 0"
                )

            # rule 8 - no em dashes (every doc)
            if EM_DASH in line:
                errors.append(
                    f"{rel(path)}:{n}: {line.count(EM_DASH)} em dash(es) on one line (rule 8); "
                    "use a colon, semicolon, comma, period, or parentheses"
                )

            # Math renders on GitHub: spacing control symbols become literal punctuation.
            for match in MATH_SPACING.finditer(line):
                errors.append(
                    f"{rel(path)}:{n}: LaTeX spacing macro {match.group(0)!r} in math; "
                    "GitHub drops the backslash and renders the punctuation literally. "
                    "Delete it (spacing is cosmetic) or use a control word like \\quad"
                )
            for match in INLINE_MATH.finditer(line):
                if match.group(1) != match.group(1).strip():
                    errors.append(
                        f"{rel(path)}:{n}: inline math {match.group(0)!r} starts/ends with a "
                        "space; GitHub may not parse it as math"
                    )

            # Specs only: instructions that outlived being carried out.
            if path in SPECS:
                for match in STALE_INTENT.finditer(line):
                    errors.append(
                        f"{rel(path)}:{n}: stale instruction {match.group(0)!r}; "
                        "if it is done, say what is, and point at it"
                    )
                for match in CODE_REF.finditer(line):
                    if not _module_exists(match.group(1)):
                        errors.append(
                            f"{rel(path)}:{n}: `{match.group(1)}` names no module or attribute "
                            "under src/; the spec describes code that does not exist"
                        )

    # rule 5: canonical docs declare what they take as given
    for name in CANONICAL:
        path = ROOT / name
        if not path.exists():
            errors.append(f"{name}: canonical doc missing")
        elif "*Assumes:" not in path.read_text(encoding="utf-8"):
            errors.append(f"{name}: no `*Assumes:*` reader line (rule 5)")

    check_depends_graph(errors)
    check_anchors(errors)

    if errors:
        print("Doc lint: FAIL")
        for e in errors:
            print(f"  - {e}")
        print(f"\n{len(errors)} issue(s). See docs/conventions.md §7.")
        return 1

    print(f"Doc lint: OK ({len(ALL_DOCS)} files, charter rules 5/8/9/11 clean).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
