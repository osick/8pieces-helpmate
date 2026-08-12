"""`--accent` must stay confined to links, focus rings and hover borders.

Why this exists: the design's central colour rule -- stated in app.css's own
header comment -- is that the accent touches links, focus rings and hover
borders only. It is never a field, never a header fill, and never the move
list, because the ordinal (Optimal -> Slower -> No mate) is deliberately
encoded with luminance and weight, not hue. That rule was verified for this
branch by a manual audit: read every `var(--accent` usage in the file by eye
and confirm each one sits on a `:focus-visible` or `:hover` rule. A manual
audit is not repeatable. Nothing stops a future edit from putting
`background: var(--accent)` back on `li.optimal` -- which is exactly what the
pre-redesign palette did -- and nothing would fail. This test makes the rule
mechanical: parse every CSS rule in app.css, and for each one that references
`var(--accent`, require `:focus-visible` or `:hover` somewhere in its
selector.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_CSS = ROOT / "src/packages/web/helpmate_web/static/css/app.css"


def _leaf_rules(css: str):
    """Yield (selector, declarations) for every brace-delimited rule with no
    nested braces inside it -- which is every real rule in this file,
    including the ones nested inside @media, since the regex only matches
    the innermost `{ ... }` pair and does not care what wraps it."""
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", without_comments):
        yield m.group(1).strip(), m.group(2)


def test_every_accent_usage_sits_on_a_focus_or_hover_selector():
    css = APP_CSS.read_text()
    checked = 0
    for selector, body in _leaf_rules(css):
        if "var(--accent" not in body:
            continue
        checked += 1
        assert ":focus-visible" in selector or ":hover" in selector, (
            f"{selector!r} references var(--accent) but is neither a "
            ":focus-visible nor a :hover rule -- the accent is confined to "
            "links, focus rings and hover borders (see app.css's header "
            "comment); a fill, field or list colour must use --ink / --sunk "
            "/ --panel instead."
        )
    # Known-good state on this branch: exactly one :focus-visible rule and
    # two :hover rules. A count that drops to zero would mean the parser (or
    # the file) broke silently rather than the rule being satisfied
    # vacuously.
    assert checked >= 3, (
        f"expected at least the 3 known var(--accent) usages, found "
        f"{checked} -- either app.css changed structurally or _leaf_rules "
        "stopped matching its rules"
    )
