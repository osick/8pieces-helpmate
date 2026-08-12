"""The head script's storage key must stay in sync with theme-mode.js.

Why this exists: `index.html` has a small inline `<script>` in `<head>` that
reads the stored theme and stamps `data-theme` before first paint, so a
dark-mode user does not get a white flash on load. A module import cannot run
that early, so the script necessarily re-implements two things
`js/lib/theme-mode.js` also owns: the storage key (`THEME_KEY`,
`"helpmate:theme"`) and which values are allowed to reach the attribute
(`"light"` / `"dark"`; everything else means "system", i.e. stamp nothing).
That duplication is deliberate and labelled in a comment, but a comment does
not detect drift. If someone renames `THEME_KEY` in the module, the module
and the head script silently disagree: the toggle writes to one key, the
pre-paint script reads another, and dark mode starts flashing white on load
again -- a failure invisible to every other test, because each half works
perfectly on its own. This test makes that drift impossible to miss by
failing loudly the moment the two disagree.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEME_MODE_JS = ROOT / "src/packages/web/helpmate_web/static/js/lib/theme-mode.js"
INDEX_HTML = ROOT / "src/packages/web/helpmate_web/static/index.html"


def _theme_key() -> str:
    text = THEME_MODE_JS.read_text()
    m = re.search(r'export const THEME_KEY\s*=\s*"([^"]+)"', text)
    assert m, f"{THEME_MODE_JS} has no `export const THEME_KEY = \"...\"`"
    return m.group(1)


def _head_script() -> str:
    text = INDEX_HTML.read_text()
    head = text.split("<head>", 1)[1].split("</head>", 1)[0]
    scripts = re.findall(r"<script>(.*?)</script>", head, re.DOTALL)
    assert scripts, f"{INDEX_HTML} has no inline <script> in <head>"
    # The pre-paint theme script is the one that touches localStorage.
    for s in scripts:
        if "localStorage" in s:
            return s
    raise AssertionError(
        f"{INDEX_HTML} head has no inline <script> that reads localStorage")


def test_head_script_uses_the_same_storage_key_as_theme_mode_js():
    key = _theme_key()
    script = _head_script()
    assert key in script, (
        f"{THEME_MODE_JS} defines THEME_KEY = {key!r}, but the inline "
        f"<head> script in {INDEX_HTML} does not reference it. The head "
        "script cannot import the module (it must run before first paint), "
        "so it hardcodes the key -- update that literal by hand whenever "
        "THEME_KEY changes."
    )


def test_head_script_only_ever_stamps_light_or_dark():
    # themeAttr() returns null -- "remove the attribute" -- for every value
    # other than "light"/"dark". The head script must agree, or a value it
    # treats as stampable but theme-mode.js treats as "system" would stamp a
    # data-theme the toggle itself would never produce.
    script = _head_script()
    literals = set(re.findall(r'===\s*"([^"]+)"', script))
    assert literals == {"light", "dark"}, (
        f"the inline <head> script in {INDEX_HTML} compares against "
        f"{literals!r}, but it must compare against exactly {{'light', "
        "'dark'}} -- those are the only values themeAttr() in "
        f"{THEME_MODE_JS} ever stamps onto the document; anything else "
        "means system, i.e. no attribute at all."
    )
