#!/usr/bin/env python3
"""Documentation linter: the enforceable subset of the writing charter.

The charter lives in ``docs/conventions.md``; this script gates the rules that can be
checked mechanically. Everything else there is review judgment.

Docs rot silently because a sentence about the code is not executable, so nothing
fails when the code moves underneath it. These checks make the checkable subset fail
loudly instead:

  - no line contains an em dash                                       [if adopted]
  - every file stays under the line cap, exemptions aside
  - no forbidden (career / positioning) word anywhere
  - no coined ``-able`` / ``-ability`` word that is not a real adjective
  - canonical docs carry an ``*Assumes:*`` line naming what they take as given
  - cross-doc ``file.md#anchor`` links resolve to a real heading
  - a spec's ``Depends on:`` IDs name real specs, and the graph is acyclic
  - a spec marked ``Implemented`` records an outcome for every box, and carries the
    ``Decisions`` section that the indexes send readers to
  - specs carry no instruction that was already carried out
  - a spec's ``pkg.x.y`` references name real modules or attributes   [if configured]
  - a ``<canonical>.md §<ID>`` reference anywhere in the repo names a section that
    file actually has                                                 [if configured]
  - math renders on GitHub: no LaTeX spacing control symbols, no ``$ x$``

A line may suppress the per-line checks (em dashes, forbidden words, math) with a
trailing ``<!-- lint-ok -->`` HTML comment, invisible when rendered. Use it sparingly;
it does not affect the length or ``*Assumes:*`` checks.

Run:  python3 scripts/lint_docs.py
Exits non-zero on any violation, printing ``path:line: message``.

Configuration is the block below. Stdlib only, no dependencies.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------------
# Configuration. Edit this block per project; everything below it is generic.
# --------------------------------------------------------------------------------

MAX_LINES = 600

# Files that grow by design and are not split: an append-only records file, a generated
# index. Paths relative to ROOT.
LINE_CAP_EXEMPT: set[str] = set()

# The committed Markdown in scope.
DOC_PATHS = sorted((ROOT / "docs").glob("**/*.md")) + [ROOT / "README.md"]

# Canonical docs that must orient their reader. Paths relative to ROOT.
CANONICAL: list[str] = [
    "docs/formulation.md",
    "docs/formulation-uncertainty.md",
    "docs/formulation-evaluation.md",
    "docs/architecture.md",
    "docs/conventions.md",
    "docs/glossary.md",
    "docs/market_reference.md",
    "docs/references.md",
]

# The reader-orientation marker. A canonical doc names what it takes as given, with
# links. A closing footer naming where the doc's reasoning lives is also good practice
# and is left to review: the two answer different questions (where to start, where to
# go next) and a doc may carry both.
ASSUMES_MARKER = "*Assumes:"

# Unambiguous career/positioning words (rule 11). "resume" is intentionally omitted
# (it collides with the verb, "resume the solve") and left to review.
FORBIDDEN = re.compile(
    r"\b(interview|interviews|interviewer|interviewing|hiring|recruiter|recruiting"
    r"|anti-candidate)\b",
    re.IGNORECASE,
)

# Per-phase work orders. The template and the index are exempt from the spec checks.
SPEC_DIR = ROOT / "docs" / "specs"
SPEC_EXEMPT = {"_TEMPLATE.md", "README.md"}

# Phase IDs, as they appear in a filename prefix and in `**Depends on:**`.
PHASE_ID = re.compile(r"\bR\d+\.\d+[a-z]?\b")

# Module references in specs, e.g. `mypkg.solver.core`. Set PACKAGE to "" to disable.
PACKAGE = "bess"
SRC_DIR = ROOT / "src"

# The canonical source-of-truth document(s), if sections in them are cited by ID from
# elsewhere in the repo (docstrings included). Set GLOB to "" to disable.
CANONICAL_DOC_GLOB = "docs/formulation*.md"
SECTION_ID = r"R\d+\.\d+[a-z]?"  # the shape of a section ID, as cited: "§R2.1b"
CANONICAL_SECTION = re.compile(rf"^## ({SECTION_ID})\.", re.M)

# Instructions that outlived being carried out and then rotted in place. Every entry
# should be a phrase that was live in a spec while the thing it demanded existed.
STALE_INTENT = re.compile(
    r"(to be recorded as ADRs|to record in `?docs/references\.md|when the module lands"
    r"|no `?formulation\.md`? text is written until|written into `?formulation\.md`? only after"
    r"|is written until .{0,20}approved)",
    re.IGNORECASE,
)

CHECK_MATH = True
CHECK_EM_DASH = True

# Coined adjectives: the commonest failure of "use the most common word that is exactly
# as precise". A word ending -able/-ability that is not a real English word should be a
# verb phrase instead. The system word list decides; the allowlist below is only for
# words it genuinely lacks (British spellings, and vocabulary newer than the list).
COINED_WORD = re.compile(r"\b([a-z]{4,}(?:abl[ey]|ability|ibility))\b", re.IGNORECASE)
# Words the system list lacks. Keep this short: everything the dictionary already knows
# is dead weight here and will drift. Add a word only after the check flags a real one.
REAL_ADJECTIVES = {
    # newer than the system word list (web2 predates software), but standard English
    "actionable",
    "auditable",
    "browsable",
    "cacheable",
    "callable",
    "clickable",
    "composable",
    "configurable",
    "debuggable",
    "deliverable",
    "deployable",
    "downloadable",
    "editable",
    "extendable",
    "filterable",
    "iterable",
    "observable",
    "parsable",
    "reproducible",
    "reusable",
    "runnable",
    "scalable",
    "schedulable",
    "scriptable",
    "searchable",
    "serializable",
    "sortable",
    "taggable",
    "testable",
    "traceable",
    "tunable",
    "upgradable",
    "uploadable",
    "observability",
    "reproducibility",
    "scalability",
    "testability",
    "traceability",
    # British and variant spellings the (US) system list omits
    "generalisable",
    "recognisable",
    "utilisable",
    "favourable",
    "tradeable",
    # terms of art the list predates: borrowed, not coined
    "equiprobable",
    "diagonalisable",
}

# This project's own vocabulary, sanctioned so the verdict does not depend on the host.
#
# `/usr/share/dict/words` is a *different dictionary on every operating system*. macOS
# ships `web2`, a 1934 Webster's of about 236,000 entries; Ubuntu ships `wamerican`, a
# modern spell-check list roughly a third that size. Neither contains the other. So a
# real word can resolve on a laptop and be flagged in CI, and the same tree lints clean
# and red depending on where it ran. Growing REAL_ADJECTIVES one CI failure at a time
# never converges, because the two lists disagree in both directions.
#
# Put every word of *this* repo's vocabulary that the host dictionary was resolving in
# here, and the check stops being a property of the machine. Regenerate rather than
# curate:
#
#     python3 scripts/lint_docs.py --vocabulary
#
# prints the list as it should stand. A word that leaves the documentation drops out of
# it, so it cannot accrete. Verify with an empty dictionary, which is a lower bound on
# any runner's:  WORD_LIST= python3 scripts/lint_docs.py
REPO_VOCABULARY: set[str] = {
    "acceptable",
    "adoptably",
    "applicability",
    "arguably",
    "attributable",
    "availability",
    "available",
    "charitably",
    "checkability",
    "checkable",
    "comfortable",
    "comparable",
    "compatibility",
    "computable",
    "considerable",
    "demonstrably",
    "dependable",
    "derivable",
    "detectable",
    "dispatchable",
    "distinguishable",
    "exchangeability",
    "exchangeable",
    "executable",
    "explainability",
    "feasibility",
    "guessable",
    "incomparable",
    "indistinguishable",
    "infeasibility",
    "injectable",
    "interchangeable",
    "interpretable",
    "knowable",
    "manageably",
    "measurability",
    "measurable",
    "measurably",
    "mistakable",
    "nonexchangeable",
    "noticeably",
    "overridable",
    "portable",
    "predictable",
    "probability",
    "profitable",
    "provable",
    "provably",
    "publishable",
    "reachability",
    "reachable",
    "readable",
    "realizable",
    "reasonable",
    "reasonably",
    "redistributable",
    "reliability",
    "reliable",
    "reliably",
    "renewable",
    "reportable",
    "representable",
    "responsibility",
    "satisfiable",
    "selectable",
    "separability",
    "separable",
    "serviceable",
    "solvable",
    "tolerable",
    "tractable",
    "transferable",
    "unavailable",
    "unavoidable",
    "unmarkable",
    "unprofitable",
    "unreachable",
    "unrepresentable",
    "unsatisfiable",
    "unstable",
    "unusable",
    "unverifiable",
    "variable",
    "verifiable",
    "verifiably",
}
REAL_ADJECTIVES |= REPO_VOCABULARY
CHECK_COINED_WORDS = True

# Prefixes stripped before looking a word up, so "unverifiable" resolves via "verifiable".
_NEGATING_PREFIXES = ("un", "in", "im", "ir", "non", "re", "dis", "over", "under")


def _load_word_list() -> set[str] | None:
    """The system word list, or None if this machine has none (check then skips)."""
    if os.environ.get("WORD_LIST") == "":  # an explicit empty list, for the check below
        return set()
    for candidate in ("/usr/share/dict/words", "/usr/dict/words"):
        try:
            with open(candidate, encoding="utf-8", errors="ignore") as fh:
                return {line.strip().lower() for line in fh if line.strip()}
        except OSError:
            continue
    return None


WORD_LIST = _load_word_list()
WORD_LIST_NOTE = (
    f"{len(WORD_LIST):,}-word system dictionary" if WORD_LIST else "no system dictionary"
)


def _is_real_word(word: str) -> bool:
    """Is this a word English already has, rather than one this repo invented?

    Four ways to resolve: the word itself, the word with a negating prefix removed, an
    ``-ability`` / ``-ibility`` nominalisation mapped back to its adjective
    ("eligibility" -> "eligible"), or an ``-ably`` / ``-ibly`` adverb mapped the same way
    ("arguably" -> "arguable"). The adverb of a real adjective is a real word; whether it
    reads well is review judgment, not a coinage.
    """
    w = word.lower()
    known = REAL_ADJECTIVES | (WORD_LIST or set())
    if w in known:
        return True
    for prefix in _NEGATING_PREFIXES:
        if w.startswith(prefix) and len(w) > len(prefix) + 3 and w[len(prefix) :] in known:
            return True
    for suffix, adjective in (
        ("ability", "able"),
        ("ibility", "ible"),
        ("ably", "able"),
        ("ibly", "ible"),
    ):
        if w.endswith(suffix) and w[: -len(suffix)] + adjective in known:
            return True
    return False


# --------------------------------------------------------------------------------
# Generic checks.
# --------------------------------------------------------------------------------

EM_DASH = "—"

# LaTeX spacing *control symbols*. GitHub's Markdown treats a backslash before ASCII
# punctuation as an escape and drops the backslash before MathJax runs, so `\,` and
# `\;` render as literal "," and ";" inside formulas. Control *words* are unaffected.
MATH_SPACING = re.compile(r"\\[,;:!]")

# Inline math whose content starts or ends with a space. GitHub may then refuse to
# parse the span as math at all.
INLINE_MATH = re.compile(r"(?<!\$)\$(?!\$)([^$\n]+?)\$(?!\$)")

CODE_REF = re.compile(rf"`({re.escape(PACKAGE)}\.[a-z_][a-z0-9_.]*)`") if PACKAGE else None
DEPENDS_LINE = re.compile(r"\*\*Depends on:\*\*(.*)")

SPECS = sorted(SPEC_DIR.glob("*.md")) if SPEC_DIR.exists() else []
SPEC_FILES = [p for p in SPECS if p.name not in SPEC_EXEMPT]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _phase_owners() -> dict[str, str]:
    """Map each phase ID to the spec file that owns it, e.g. {"R1.2": "core.md"}.

    A spec claims phase IDs two ways: from a filename prefix, and from a ``**Phases:**``
    line, which is how a *merged* spec declares the several phases it absorbed. Reading
    both is what lets the ``Depends on:`` graph survive a merge.
    """
    owners: dict[str, str] = {}
    for p in SPEC_FILES:
        m = re.match(r"(R\d+\.\d+[a-z]?)[-_]", p.name)
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
    """Does `bess.a.b` name a real module, package, or an attribute defined in one?

    Known limitation: the trailing-attribute test below is a word search in the
    module's text, not symbol resolution, so a spec naming a symbol that has moved
    *within* a surviving package still passes. That produced a false negative during
    S1. If this is ever tightened, `check_canonical_sections` is the pattern to
    follow: resolve the real owners first, then check membership.
    """
    parts = dotted.split(".")
    for cut in range(len(parts), 1, -1):
        base = SRC_DIR / Path(*parts[:cut])
        if base.with_suffix(".py").exists() or (base / "__init__.py").exists():
            if cut == len(parts):
                return True
            src = (
                base.with_suffix(".py")
                if base.with_suffix(".py").exists()
                else base / "__init__.py"
            )
            text = src.read_text(encoding="utf-8")
            return all(re.search(rf"\b{re.escape(a)}\b", text) for a in parts[cut:])
    return False


def check_depends_graph(errors: list[str]) -> None:
    """Every `Depends on:` ID resolves to a real spec, and the graph is acyclic."""
    owners = _phase_owners()
    if not owners:
        return
    edges: dict[str, set[str]] = {}
    for path in SPEC_FILES:
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

    state: dict[str, int] = {}

    def visit(node: str, trail: list[str]) -> None:
        if state.get(node) == 1:
            cycle = " -> ".join(trail[trail.index(node) :] + [node])
            errors.append(f"{rel(SPEC_DIR)}: `Depends on:` cycle {cycle}")
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
    """Every cross-doc `file.md#anchor` link resolves to a real anchor.

    Catches links left behind when a heading is reworded, which read as fine in the
    source and silently land at the top of the page.

    An anchor is a heading slug, an explicit ``<a id="...">`` or ``<a name="...">``, or
    a ``{#custom-id}`` attribute. A long records file typically anchors each record
    explicitly so the links survive a retitling, and those must count.
    """
    headings: dict[Path, set[str]] = {}
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        headings[path] = {_gh_slug(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}
        headings[path] |= set(re.findall(r'<a [^>]*(?:id|name)="([^"]+)"', text))
        headings[path] |= set(re.findall(r"\{#([^}\s]+)\}", text))

    link = re.compile(r"\]\(([^)\s#]*\.md)#([\w-]+)\)")
    for path in DOC_PATHS:
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
    """A spec claiming `Implemented` has no unrecorded box, and carries `Decisions`.

    Ticking is the only record that a gate was actually run, and "we meant to tick it"
    is indistinguishable from "it passed" a few weeks later. A box has three states:
    ``- [x]`` ran and passed, ``- [!]`` ran and did not pass (outcome written beside
    it), and ``- [ ]`` no record either way. Only the third blocks.
    """
    status = re.compile(r"^\*\*Status:\*\*\s*(\w+)", re.M)
    for path in SPEC_FILES:
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
            errors.append(f"{rel(path)}: no `## Decisions` section (the reasoning trail)")


def check_canonical_sections(errors: list[str]) -> None:
    """A `<canonical>.md ... §<ID>` reference names a section that exists there.

    When the canonical document is split across several files by subject, the split is
    invisible to a docstring: naming the wrong companion file next to a section number
    reads perfectly well and points nowhere. Scope is the whole repository, because the
    anchor check above only sees Markdown links inside the doc set, so a section that
    moves files leaves every source reference to it silently wrong.
    """
    if not CANONICAL_DOC_GLOB:
        return
    owners: dict[str, set[str]] = {}
    for path in sorted(ROOT.glob(CANONICAL_DOC_GLOB)):
        owners[path.name] = set(CANONICAL_SECTION.findall(path.read_text(encoding="utf-8")))
    if not owners:
        errors.append(f"docs: no files match {CANONICAL_DOC_GLOB!r}")
        return

    stem = re.escape(Path(CANONICAL_DOC_GLOB).name.split("*")[0])
    # The separator may span one newline, since docstrings wrap mid-reference; matching
    # over the whole text rather than line by line keeps each reference counted once.
    ref = re.compile(
        rf"({stem}[a-z-]*)\.md`{{0,2}}[^§\n]{{0,60}}\n?[^§\n]{{0,20}}§\s?({SECTION_ID})"
    )
    skip = {
        ".venv", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".hypothesis", "node_modules", "planning",
    }  # fmt: skip
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in {".py", ".md"} or any(s in path.parts for s in skip):
            continue
        text = path.read_text(encoding="utf-8")
        for m in ref.finditer(text):
            line_no = text.count("\n", 0, m.start()) + 1
            if "lint-ok" in text.splitlines()[line_no - 1]:
                continue
            name, section = f"{m.group(1)}.md", m.group(2)
            if name not in owners:
                errors.append(f"{rel(path)}:{line_no}: `{name}` is not a canonical doc")
            elif section not in owners[name]:
                home = [f for f, s in owners.items() if section in s]
                where = f"; §{section} lives in {home[0]}" if home else ""
                errors.append(f"{rel(path)}:{line_no}: `{name}` has no §{section} section{where}")


def main() -> int:
    errors: list[str] = []

    for path in DOC_PATHS:
        lines = path.read_text(encoding="utf-8").splitlines()

        if len(lines) > MAX_LINES and rel(path) not in LINE_CAP_EXEMPT:
            errors.append(
                f"{rel(path)}: {len(lines)} lines over the {MAX_LINES}-line cap "
                "(rule 9): split it, "
                "or add it to LINE_CAP_EXEMPT if it grows by design"
            )

        for n, line in enumerate(lines, 1):
            # Inline escape hatch for the per-line checks; use sparingly, for instance
            # on a line that must quote a banned word.
            if "<!-- lint-ok" in line:
                continue

            for match in FORBIDDEN.finditer(line):
                errors.append(
                    f"{rel(path)}:{n}: forbidden word {match.group(0)!r} "
                    "(rule 11): strategy stays Tier 0"
                )

            if CHECK_EM_DASH and EM_DASH in line:
                errors.append(
                    f"{rel(path)}:{n}: {line.count(EM_DASH)} em dash(es) on one line (rule 8); "
                    "use a colon, semicolon, comma, period, or parentheses"
                )

            if CHECK_COINED_WORDS and WORD_LIST is not None:
                for match in COINED_WORD.finditer(line):
                    word = match.group(1)
                    if _is_real_word(word):
                        continue
                    errors.append(
                        f"{rel(path)}:{n}: coined word {word!r}; English has no such "
                        "adjective, so write the verb phrase instead (or add it to "
                        "REAL_ADJECTIVES if this really is a word)"
                    )

            if CHECK_MATH:
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

            if path in SPEC_FILES:
                for match in STALE_INTENT.finditer(line):
                    errors.append(
                        f"{rel(path)}:{n}: stale instruction {match.group(0)!r}; "
                        "if it is done, say what is, and point at it"
                    )
                if CODE_REF is not None:
                    for match in CODE_REF.finditer(line):
                        if not _module_exists(match.group(1)):
                            errors.append(
                                f"{rel(path)}:{n}: `{match.group(1)}` names no module or "
                                f"attribute under {rel(SRC_DIR)}/; the spec describes code "
                                "that does not exist"
                            )

    for name in CANONICAL:
        path = ROOT / name
        if not path.exists():
            errors.append(f"{name}: canonical doc missing")
        elif ASSUMES_MARKER not in path.read_text(encoding="utf-8"):
            errors.append(f"{name}: no `*Assumes:*` reader line (rule 5)")

    check_depends_graph(errors)
    check_anchors(errors)
    check_canonical_sections(errors)
    check_spec_status(errors)

    if errors:
        print("Doc lint: FAIL")
        for e in errors:
            print(f"  - {e}")
        print(f"\n{len(errors)} issue(s), {WORD_LIST_NOTE}. See docs/conventions.md \u00a77.")
        return 1

    print(f"Doc lint: OK ({len(DOC_PATHS)} files, {WORD_LIST_NOTE}).")
    return 0


def print_vocabulary() -> int:
    """Print REPO_VOCABULARY as it should stand: every -able word only the host resolves.

    Run this instead of hand-editing the set. It answers the question the set exists for,
    "which words is this repo leaning on the machine's dictionary for", and the answer is
    derived from the documentation rather than accumulated from CI failures.
    """
    global WORD_LIST, REAL_ADJECTIVES
    WORD_LIST, REAL_ADJECTIVES = set(), REAL_ADJECTIVES - REPO_VOCABULARY
    need = set()
    for path in DOC_PATHS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "<!-- lint-ok" in line:
                continue
            for match in COINED_WORD.finditer(line):
                word = match.group(1).lower()
                if not _is_real_word(word):
                    need.add(word)
    print("REPO_VOCABULARY = {")
    line = "   "
    for word in sorted(need):
        item = f' "{word}",'
        if len(line) + len(item) > 92:
            print(line)
            line = "   "
        line += item
    if line.strip():
        print(line)
    print("}")
    print(
        f"\n# {len(need)} word(s). Paste over the set above; do not merge by hand.", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    if "--vocabulary" in sys.argv:
        sys.exit(print_vocabulary())
    sys.exit(main())
