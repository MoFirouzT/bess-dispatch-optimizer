// GitHub renders $...$ and $$...$$ natively; MkDocs needs arithmatex plus this to
// match, so the same Markdown produces the same formulas in both places.
window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
    processEnvironments: true,
  },
  // `arithmatex` is the span the extension wraps body math in, and only that span is
  // typeset. Known limitation, not worth working around: the table of contents is built
  // from heading *text*, so the span is stripped and the two headings in formulation.md
  // that contain math show their raw delimiters in the sidebar. Widening this to the nav
  // does not fix it. Rewording those headings would, and would also change their anchors,
  // which other docs link to and scripts/lint_docs.py checks, so they stay as they are.
  options: { ignoreHtmlClass: ".*|", processHtmlClass: "arithmatex" },
};

document$.subscribe(() => {
  MathJax.startup.output.clearCache();
  MathJax.typesetClear();
  MathJax.texReset();
  MathJax.typesetPromise();
});
