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
  - a ``formulation*.md §R<n>.<m>`` reference, anywhere in the repo, names a
    section that file actually has (docstrings included, since the anchor check
    above only sees Markdown links under ``docs/``)
  - a spec marked ``Implemented`` records an outcome for every box (``- [x]`` passed,
    ``- [!]`` ran and did not), and every spec carries the ``Decisions`` section that
    the indexes send readers to

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
    "docs/formulation-uncertainty.md",
    "docs/formulation-evaluation.md",
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


def _phase_owners() -> dict[str, str]:
    """Map each phase ID to the spec file that owns it, e.g. {"R1.2": "dispatch-core.md"}.

    A spec claims phase IDs two ways: from its filename (``stochastic-dispatch.md``)
    and from a ``**Phases:**`` line, which is how a *merged* spec declares the several
    phases it absorbed. Reading both is what lets the ``Depends on:`` graph survive a
    merge: a spec depending on R1.1 still resolves after R1.1 folded into `dispatch-core`.
    """
    owners: dict[str, str] = {}
    for p in SPECS:
        if p.name in {"_TEMPLATE.md", "README.md"}:
            continue
        m = re.match(r"(R\d+\.\d+[a-z]?)-", p.name)
        if m:
            owners[m.group(1)] = p.name
        line = re.search(
            r"^\*\*Phases:\*\*(.*(?:\n(?!\*\*|\n).*)*)", p.read_text(encoding="utf-8"), re.M
        )
        if line:
            for pid in PHASE_ID.findall(line.group(1)):
                owners[pid] = p.name
    return owners


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
    owners = _phase_owners()
    edges: dict[str, set[str]] = {}
    for path in SPECS:
        if path.name in {"_TEMPLATE.md", "README.md"}:
            continue
        line = DEPENDS_LINE.search(path.read_text(encoding="utf-8"))
        if not line:
            continue
        deps = set()
        for dep in PHASE_ID.findall(line.group(1)):
            target = owners.get(dep)
            if target is None:
                errors.append(
                    f"{rel(path)}: `Depends on:` names {dep}, which no spec owns "
                    f"(known: {', '.join(sorted(owners))})"
                )
                continue
            if target != path.name:  # a merged spec may list its own absorbed phases
                deps.add(target)
        edges[path.name] = deps

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


def check_spec_status(errors: list[str]) -> None:
    """A spec claiming `Implemented` has no *unrecorded* box, and carries a `Decisions` section.

    Ticking is the only record that a gate was actually run, and "we meant to tick it"
    is indistinguishable from "it passed" a few weeks later. R2.1e shipped as
    Implemented with seven unticked acceptance boxes and nothing caught it.

    A box therefore has **three** states, not two:

    - ``- [x]`` ran and passed
    - ``- [!]`` ran and did not pass, or was conditional on something that did not
      happen; the outcome is written on the line beside it
    - ``- [ ]`` no record either way, which is what this check exists to catch

    The third is the only one that blocks. Before ``- [!]`` existed a phase whose honest
    result was "the gate says no" could not be marked Implemented at all, which left two
    bad options: tick boxes that failed, or leave a finished phase in limbo. R2.9 is the
    first: its search found a 4.5% narrower NL interval and its own per-hour constraint
    rejected it. A ``- [!]`` line carries the measured number, so it is not confusable
    with a box nobody filled in.

    The `Decisions` heading is checked because two index files send readers there for
    a phase's reasoning; four different names for that section had drifted in before
    they were normalized.
    """
    status = re.compile(r"^\*\*Status:\*\*\s*(\w+)", re.M)
    for path in SPECS:
        if path.name in {"_TEMPLATE.md", "README.md"}:  # the template and the ledger
            continue
        text = path.read_text(encoding="utf-8")
        m = status.search(text)
        if not m:
            errors.append(f"{rel(path)}: no `**Status:**` line")
            continue
        if m.group(1) == "Implemented":
            open_boxes = [
                n for n, line in enumerate(text.splitlines(), 1) if line.strip().startswith("- [ ]")
            ]
            if open_boxes:
                lines = ", ".join(str(n) for n in open_boxes[:5])
                more = f" (+{len(open_boxes) - 5} more)" if len(open_boxes) > 5 else ""
                errors.append(
                    f"{rel(path)}: status is Implemented but {len(open_boxes)} box(es) "
                    f"have no recorded outcome, at line {lines}{more}; tick `- [x]` if "
                    "it passed, or mark `- [!]` and write what happened beside it"
                )
            bare_failures = [
                n
                for n, line in enumerate(text.splitlines(), 1)
                if line.strip().startswith("- [!]") and len(line.strip()) < 20
            ]
            if bare_failures:
                lines = ", ".join(str(n) for n in bare_failures)
                errors.append(
                    f"{rel(path)}: `- [!]` box with no outcome written beside it, at "
                    f"line {lines}; the marker only means something with the measured "
                    "result on the line"
                )
        if not re.search(r"^## Decisions\b", text, re.M):
            errors.append(f"{rel(path)}: no `## Decisions` section (the phase's reasoning trail)")


def check_formulation_sections(errors: list[str]) -> None:
    """A `formulation*.md ... §R<n>.<m>` reference names a section that exists there.

    The formulation is split across three files by subject, and the split is invisible
    to a docstring: naming the wrong companion file next to a section number reads
    perfectly well and points nowhere. Module and test docstrings are the exposed
    surface, because the anchor check above only sees Markdown links inside ``docs/``,
    so a section that moves files leaves every ``src/`` reference to it silently wrong.

    Scope is therefore the whole repository, not just the doc set. ``planning/`` is
    excluded: it is Tier 0, gitignored, and not ours to keep consistent.
    """
    owners: dict[str, set[str]] = {}
    for path in sorted(ROOT.glob("docs/formulation*.md")):
        secs = re.findall(r"^## (R\d+\.\d+[a-z]?)\.", path.read_text(encoding="utf-8"), re.M)
        owners[path.name] = set(secs)
    if not owners:
        errors.append("docs: no formulation*.md files found")
        return

    # `formulation-uncertainty.md` (any quoting) followed by a section marker. The
    # separator may span one newline, since docstrings wrap mid-reference; matching
    # over the whole text rather than line by line keeps each reference counted once.
    ref = re.compile(
        r"formulation(-[a-z]+)?\.md`{0,2}[^§\n]{0,60}\n?[^§\n]{0,20}§\s?(R\d+\.\d+[a-z]?)"
    )
    skip = {
        ".venv", ".git", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".hypothesis", "planning",
    }  # fmt: skip
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in {".py", ".md"} or any(s in path.parts for s in skip):
            continue
        text = path.read_text(encoding="utf-8")
        for m in ref.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            if "lint-ok" in text.splitlines()[line_no - 1]:
                continue
            name = f"formulation{m.group(1) or ''}.md"
            section = m.group(2)
            if name not in owners:
                errors.append(f"{rel(path)}:{line_no}: `{name}` is not a formulation file")
            elif section not in owners[name]:
                home = [f for f, s in owners.items() if section in s]
                where = f"; §{section} lives in {home[0]}" if home else ""
                errors.append(f"{rel(path)}:{line_no}: `{name}` has no §{section} section{where}")


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
    check_formulation_sections(errors)
    check_spec_status(errors)

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
