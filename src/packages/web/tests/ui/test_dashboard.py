import json
import re
from urllib.parse import quote, urlparse, parse_qs

import pytest

GOLDEN = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"


def test_dashboard_renders_the_initial_position(page, server):
    page.goto(server)
    page.wait_for_function("window.__explorerReady !== undefined")
    page.wait_for_selector("#move-list li")
    assert "dtm 2" in page.inner_text("#position-summary")
    sans = page.eval_on_selector_all("#move-list li", "els => els.map(e => e.dataset.san)")
    assert "Kh6" in sans and "Kh8" in sans
    optimal = page.eval_on_selector_all("#move-list li.optimal", "els => els.map(e => e.dataset.san)")
    assert set(optimal) == {"Kh6", "Kh8"}


def test_clicking_a_move_advances_and_history_returns(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li.optimal")
    before = page.input_value("#fen-input")
    page.click("#move-list li.optimal")
    page.wait_for_function(
        "before => document.getElementById('fen-input').value !== before", arg=before)
    assert page.input_value("#fen-input") != before
    assert "fen=" in page.url
    page.click("#btn-back")
    page.wait_for_function(
        "before => document.getElementById('fen-input').value === before", arg=before)


def test_a_shared_link_restores_the_position(page, server):
    page.goto(f"{server}/#fen={quote(GOLDEN)}")
    page.wait_for_selector("#move-list li")
    assert page.input_value("#fen-input") == GOLDEN


def test_setting_an_invalid_fen_shows_the_server_message(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.fill("#fen-input", "garbage")
    page.press("#fen-input", "Enter")
    page.wait_for_selector("#error-banner:not([hidden])")
    assert page.inner_text("#error-banner")


def test_materials_panel_lists_tables_and_opens_a_sample(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    names = page.eval_on_selector_all("#material-list li", "els => els.map(e => e.dataset.material)")
    assert "KQvk" in names and "Kvk" in names
    page.click("#material-list li[data-material=KQvk]")
    page.wait_for_selector("#material-samples li")


def test_only_the_active_panel_is_visible(page, server):
    # Regression: `#panel-explorer { display: flex }` is an id selector and
    # outranks the user-agent [hidden] rule, so every panel rendered at once.
    # This is a general CSS/DOM invariant, nothing mining-specific -- kept on
    # the shipped default (search off) so the nav is still exercised via a
    # real click on that config, not only via #panel=... hash deep links.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.is_visible("#panel-explorer")
    assert not page.is_visible("#panel-materials")
    # #panel-mine does not exist at all on a search-off server. is_visible()
    # returns False for a selector that matches nothing, so it would pass
    # here trivially whether the element were absent or merely hidden --
    # assert absence explicitly instead of leaning on that coincidence.
    assert page.locator("#panel-mine").count() == 0

    page.click("nav button[data-panel=materials]")
    assert not page.is_visible("#panel-explorer")
    assert page.is_visible("#panel-materials")


def test_switching_into_the_mine_panel_hides_the_others(page, server_mining):
    # The mine leg of the panel-visibility regression above: needs a server
    # that actually has #panel-mine in the document, split out rather than
    # folded into test_only_the_active_panel_is_visible so that test can stay
    # on the shipped default.
    page.goto(server_mining)
    page.wait_for_selector("#move-list li")
    page.click("nav button[data-panel=materials]")
    assert page.is_visible("#panel-materials")

    page.click("nav button[data-panel=mine]")
    assert not page.is_visible("#panel-materials")
    assert page.is_visible("#panel-mine")


def test_material_stats_render_both_histograms(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    page.click("#material-list li[data-material=KQvk]")
    page.wait_for_selector("#dtm-hist")
    assert int(page.get_attribute("#dtm-hist", "data-rows")) > 0
    assert int(page.get_attribute("#uniqueness-hist", "data-rows")) > 0
    # the cell tiles must add up the way the API reports them
    tiles = page.eval_on_selector_all("#cell-summary .v", "els => els.map(e => e.textContent)")
    assert len(tiles) == 4
    nums = [int(t.replace(",", "")) for t in tiles]
    assert nums[0] + nums[1] + nums[2] == nums[3]
    # the first bar is labelled in h# notation, not raw plies
    assert page.eval_on_selector("#dtm-hist .k", "e => e.textContent").startswith("h#")


def _square_box(page, square):
    return page.locator(f"#board rect[data-square={square}]").bounding_box()


def _drag_square_to_square(page, frm, to):
    a, b = _square_box(page, frm), _square_box(page, to)
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=10)
    page.mouse.up()


def test_a_legal_drag_plays_the_move(page, server):
    # 8/7k/5K2/8/8/8/8/6Q1 b: Black to move, Kh7 may go to h8, landing on
    # 7k/8/5K2/8/8/8/8/6Q1 w -- dtm 1 (h#0.5), 1 optimal line. Measured
    # against the KPvk fixture (whose closure contains KQvk) on 2026-08-12.
    #
    # render() never clears #position-summary before its /v1/moves await
    # (only the move list, lines and themes), so a bare "dtm" substring
    # check here is satisfied instantly by the PARENT's own verdict, still
    # on screen from before the drag ever happened -- proven by fix round
    # 1's route-blocking run, recorded in the report. Assert the actual
    # child answer instead, which can only appear once the real fetch for
    # THIS position has landed.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector("#stm-select", "e => e.value") == "b"
    _drag_square_to_square(page, "h7", "h8")
    page.wait_for_function(
        "() => document.getElementById('stm-select').value === 'w'")
    assert "8/7k" not in page.input_value("#fen-input")
    page.wait_for_function(
        "() => document.getElementById('position-summary').textContent === "
        "'dtm 1 (h#0.5) · 1 optimal line(s)'")


def test_an_illegal_drag_relocates_and_keeps_the_side_to_move(page, server):
    # The white queen cannot legally move at all here -- it is Black's turn --
    # so dragging it is unambiguously a relocation, landing on
    # 8/7k/5K2/8/3Q4/8/8/8 b -- dtm 2 (h#1), 1 optimal line (Kh6 the only
    # answer, the queen having lost its original mating square). Measured
    # against the KPvk fixture on 2026-08-12.
    #
    # Same defect as test_a_legal_drag_plays_the_move above: a bare
    # `includes('dtm')` wait is satisfied in under a millisecond by the
    # PRE-drag summary, never actually observing the recomputed verdict --
    # proven by fix round 1's route-blocking run. Assert the real,
    # recomputed text.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    _drag_square_to_square(page, "g1", "d4")
    page.wait_for_function(
        "() => document.getElementById('fen-input').value.startsWith('8/7k/5K2/8/3Q4/')")
    assert page.eval_on_selector("#stm-select", "e => e.value") == "b", "a relocation flipped the turn"
    page.wait_for_function(
        "() => document.getElementById('position-summary').textContent === "
        "'dtm 2 (h#1) · 1 optimal line(s)'")


def test_back_undoes_a_relocation(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    before = page.input_value("#fen-input")
    _drag_square_to_square(page, "g1", "d4")
    page.wait_for_function(
        "b => document.getElementById('fen-input').value !== b", arg=before)
    page.click("#btn-back")
    page.wait_for_function(
        "b => document.getElementById('fen-input').value === b", arg=before)


def test_a_relocation_reaches_the_url(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    _drag_square_to_square(page, "g1", "d4")
    page.wait_for_function("() => location.hash.includes('3Q4')")


def test_a_failed_evaluation_clears_the_move_lookup(page, server):
    # H1 from the v0.12.0 whole-branch review. render()'s kingProblem branch
    # clears lastMoves; the ApiError branch did not. A drag after a failed
    # evaluation then matched against the PREVIOUS position's moves and
    # navigated to that move's child -- discarding the user's edit and
    # rewriting the URL to a position they never built.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    # Put the kings adjacent: legal to build, impossible to probe.
    _drag_square_to_square(page, "f6", "g6")
    page.wait_for_selector("#error-banner:not([hidden])")
    assert page.eval_on_selector_all("#move-list li", "e => e.length") == 0
    broken = page.input_value("#fen-input")
    # This drag corresponds to a move that was legal in the PREVIOUS position.
    _drag_square_to_square(page, "h7", "h8")
    page.wait_for_timeout(400)
    final = page.input_value("#fen-input")
    assert final != "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", \
        "the board jumped back to a stale position"
    assert "5K2" not in final, \
        "the white king reappeared on f6 -- the stale move list was replayed"
    assert final != broken, "the drag was silently swallowed"


def test_a_pending_download_clears_the_move_lookup_too(page, server):
    # Fix round 1 (code review): the 202 branch was the SAME hazard as H1
    # above, but worse -- it needs no coincidental uci match and is reachable
    # on a routine "downloading..." banner, not only after the retry cap.
    # board.setPosition() and syncControls() at the top of render() have
    # already moved the board and the FEN field to the clicked/dragged
    # position by the time the 202 arrives, so a previous position's move
    # list left on screen let a stale drag navigate to a child of a position
    # no longer displayed -- and worse, to a FEN that didn't even reflect
    # what was actually on the board (see the queen below).
    page.goto(server)
    page.wait_for_selector("#move-list li")
    start = page.input_value("#fen-input")

    # From here on, every /v1/moves call reports "still downloading" --
    # exactly what a fresh install, or navigating into newly-mined material,
    # produces routinely.
    page.route("**/v1/moves**", lambda route: route.fulfill(
        status=202, content_type="application/json",
        body='{"status": "fetching", "material": "KQvk"}'))

    # Relocate the queen, not a king: kings stay non-adjacent, so this
    # (unlike H1's own kingProblem trigger) actually reaches api.moves() and
    # gets the mocked 202. The black king is untouched and stays on h7.
    _drag_square_to_square(page, "g1", "g6")
    page.wait_for_selector("#error-banner:not([hidden])")
    assert page.eval_on_selector_all("#move-list li", "e => e.length") == 0
    pending = page.input_value("#fen-input")
    assert pending != start, "the queen relocation was silently swallowed"

    # h7h8 was legal in the STARTING position only, before the queen ever
    # moved. If lastMoves were still the starting position's, this would
    # match it and navigate to the starting position's OWN h7h8 child --
    # silently undoing the queen relocation above along the way.
    _drag_square_to_square(page, "h7", "h8")
    page.wait_for_timeout(400)
    final = page.input_value("#fen-input")
    assert final != pending, "the drag was silently swallowed"
    assert "5K2" not in final, \
        "the board reverted to the stale child fen -- the queen relocation " \
        "was undone and the stale move list was replayed"


PROMOTION_START = "7k/4P3/5K2/8/8/8/8/8 w - - 0 1"


def test_a_multi_candidate_promotion_drag_waits_for_the_dialog(page, server):
    # e7-e8 alone is ambiguous -- four legal moves share the uci prefix
    # (e7e8q/e7e8r/e7e8b/e7e8n) -- so this is the one path playedMove
    # actually guards: validateMoveInput shows the dialog and returns
    # before any piece is chosen, moveInputFinished fires a microtask
    # later (well before the user has clicked anything), and without the
    # flag commitPlacement() would commit whatever cm-chessboard's own
    # movePiece() already dropped on e8 -- a bare, unpromoted pawn -- as a
    # bogus relocation. Measured against a freshly generated KPvk table on
    # 2026-08-12: dtm 3 (h#1.5) to start; e7e8q -> dtm 4 (h#2), 29 optimal
    # lines (e7e8n/e7e8b are dead: not solvable at all).
    page.goto(f"{server}/#fen={quote(PROMOTION_START)}")
    page.wait_for_selector("#move-list li")
    before = page.input_value("#fen-input")

    _drag_square_to_square(page, "e7", "e8")

    page.wait_for_selector(".promotion-dialog-button[data-piece=wq]")
    # The dialog is up and nothing has been picked yet: the position on
    # screen must still be the one the drag started from.
    assert page.input_value("#fen-input") == before

    page.click(".promotion-dialog-button[data-piece=wq]")
    page.wait_for_function(
        "() => document.getElementById('fen-input').value.startsWith('4Q2k/8/5K2/')")
    # Same staleness trap as test_a_legal_drag_plays_the_move: the summary
    # is not cleared before the /v1/moves await, so read it only once it has
    # actually become the CHILD's verdict, not the STARTING position's.
    page.wait_for_function(
        "() => document.getElementById('position-summary').textContent === "
        "'dtm 4 (h#2) · 29 optimal line(s)'")

    page.click("#btn-back")
    page.wait_for_function(
        "b => document.getElementById('fen-input').value === b", arg=before)


def test_the_trays_flank_the_board_black_above_white_below(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    black = page.eval_on_selector("#tray-black", "e => e.getBoundingClientRect()")
    white = page.eval_on_selector("#tray-white", "e => e.getBoundingClientRect()")
    assert black["bottom"] <= board["top"] + 1, "the black tray is not above the board"
    assert white["top"] >= board["bottom"] - 1, "the white tray is not below the board"


def test_the_trays_swap_when_the_board_is_flipped(page, server):
    # The placement is only meaningful because each tray sits on its own
    # colour's side; after a flip, black is at the bottom and so is its tray.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.click("#btn-flip")
    page.wait_for_function(
        "() => document.getElementById('tray-black').getBoundingClientRect().top"
        " > document.getElementById('board').getBoundingClientRect().top")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    black = page.eval_on_selector("#tray-black", "e => e.getBoundingClientRect()")
    white = page.eval_on_selector("#tray-white", "e => e.getBoundingClientRect()")
    assert black["top"] >= board["bottom"] - 1, "the black tray did not move below"
    assert white["bottom"] <= board["top"] + 1, "the white tray did not move above"


def test_the_fen_applies_on_enter_without_a_set_button(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector_all("#fen-form button[type=submit]", "e => e.length") == 0
    page.fill("#fen-input", "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1")
    page.press("#fen-input", "Enter")
    page.wait_for_function(
        "() => document.getElementById('stm-select').value === 'w'")


def test_the_fen_input_has_its_own_row_and_the_rest_share_one_line(page, server):
    # Fix round 1: a 460px rail can't fit a FEN input, a select and three
    # buttons on one line (measured: 764px of children in a 428px content
    # box) -- the first cut's "one line" comment and the report that verified
    # it were both wrong. The real, deliberate layout is two rows: the FEN
    # input alone (it's the longest datum here, ~30 characters), then
    # everything else -- To move / Flip / Clear board / Back, 335px against
    # the same 428px -- sharing a single line at the >=860px breakpoint.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    fen = page.eval_on_selector("#fen-input", "e => e.getBoundingClientRect()")
    select = page.eval_on_selector("#stm-select", "e => e.getBoundingClientRect()")
    flip = page.eval_on_selector("#btn-flip", "e => e.getBoundingClientRect()")
    clear = page.eval_on_selector("#btn-clear-board", "e => e.getBoundingClientRect()")
    back = page.eval_on_selector("#btn-back", "e => e.getBoundingClientRect()")
    assert select["top"] >= fen["bottom"] - 1, "the FEN input does not have its own row"
    tops = [select["top"], flip["top"], clear["top"], back["top"]]
    # align-items: center puts a <label> wrapping a <select> at a slightly
    # different top than a plain <button> even on the same line (their
    # heights differ by a few px), so the same-row tolerance is generous --
    # a genuine wrap to a second line differs by a full row height (~30px+
    # the row gap), nowhere close to this margin.
    assert max(tops) - min(tops) <= 8, "the remaining controls do not share one row"


def test_the_board_has_no_mode_controls(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    for gone in ("#btn-erase", "#btn-arrange", "#btn-done-editing", "#edit-hint"):
        assert page.eval_on_selector_all(gone, "e => e.length") == 0, f"{gone} still exists"
    # and a tray piece is draggable without arming anything first
    assert page.eval_on_selector_all(
        ".tray button[aria-pressed]", "e => e.length") == 0


def test_clearing_the_board_names_the_missing_kings(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.click("#btn-clear-board")
    page.wait_for_function(
        "document.getElementById('position-summary').textContent.includes('kings')")
    # and it says so without spending a request that can only 400
    assert page.is_hidden("#error-banner")


def test_the_server_chip_reports_what_is_loaded(page, server):
    page.goto(server)
    page.wait_for_function("window.__chipReady === true")
    chip = page.inner_text("#server-chip")
    assert "tables" in chip
    assert "unreachable" not in chip


def test_mine_search_and_client_side_validation(page, server_mining):
    page.goto(f"{server_mining}/#panel=mine")
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.fill("#mine-form input[name=count]", "4")
    page.fill("#mine-form input[name=starts]", "2")
    page.fill("#mine-form input[name=ends]", "4")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#mine-results li")
    assert "position(s)" in page.inner_text("#mine-status")

    # starts > count is caught before any request
    page.fill("#mine-form input[name=count]", "2")
    page.fill("#mine-form input[name=starts]", "5")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('cannot exceed')")


def test_theme_picker_is_populated_from_the_server(page, server_mining):
    page.goto(f"{server_mining}/#panel=mine")
    page.wait_for_selector("#mine-themes option")
    values = page.eval_on_selector_all(
        "#mine-themes option", "els => els.map(e => e.value)")
    assert "model" in values and "closed-walk" in values


def test_theme_picker_marks_themes_that_answer_on_saturated_positions(page, server_mining):
    # Task 10: any theme whose `needs` isn't "solutions" still answers on
    # positions whose stored solution count has saturated (capped at 255) --
    # the picker must mark those, driven by the server's own `needs` field,
    # not by a hard-coded theme name.
    import urllib.request
    with urllib.request.urlopen(f"{server_mining}/v1/themes") as r:
        registry = json.load(r)["themes"]
    non_solutions = {t["name"] for t in registry if t["needs"] != "solutions"}
    assert non_solutions, "fixture build must register at least one non-Solutions theme"

    page.goto(f"{server_mining}/#panel=mine")
    page.wait_for_selector("#mine-themes option")
    options = page.eval_on_selector_all(
        "#mine-themes option",
        "els => els.map(e => ({value: e.value, title: e.title}))")
    by_value = {o["value"]: o["title"] for o in options}
    for name in non_solutions:
        assert "saturated" in by_value[name].lower()
    solutions_names = {t["name"] for t in registry if t["needs"] == "solutions"}
    for name in solutions_names:
        assert "saturated" not in by_value[name].lower()


def test_selecting_two_themes_sends_both_not_just_the_last(page, server_mining):
    # Regression: Object.fromEntries(new FormData(form).entries()) keeps only
    # the LAST value of a repeated field. A naive read of the multi-select
    # would silently narrow a two-theme search down to one -- the exact class
    # of bug this project has hit before, so assert on the actual request the
    # browser sends rather than trusting the picker looks right on screen.
    page.goto(f"{server_mining}/#panel=mine")
    page.wait_for_selector("#mine-themes option")
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.select_option("#mine-themes", ["model", "mirror"])
    with page.expect_request(lambda r: "/v1/mine" in r.url) as req_info:
        page.click("#mine-form button[type=submit]")
    qs = parse_qs(urlparse(req_info.value.url).query)
    assert qs.get("theme") == ["model", "mirror"]


def test_explorer_shows_detected_themes(page, server):
    page.goto(f"{server}/#fen={quote(GOLDEN)}")
    page.wait_for_function(
        "() => document.getElementById('position-themes').textContent.length > 0")
    text = page.inner_text("#position-themes")
    # Measured against a freshly generated KQvk table (GET
    # /v1/probe?themes=true, re-checked 2026-08-09 after the round-2 themes
    # landed): {"themes": ["set-play", "pure", "model", "ideal", "mirror",
    # "single-piece", "single-piece:white", "single-piece:black"]}. set-play
    # (Needs::Plane, sorts first in registry order) legitimately fires here:
    # the same position with the other side to move is solvable. Assert the
    # actual rendered content, not just that something is there -- a smoke
    # check here would pass with the themes_note/themeSummary priority
    # reversed, or with an entirely wrong theme list.
    assert text == ("set-play · pure · model · ideal · mirror · single-piece · "
                     "single-piece:white · single-piece:black")


def test_explorer_shows_the_flip_note_not_no_themes_detected(page, server):
    # Regression: a colour-flipped position (answered via the fixture's only
    # table, KQvk, by swapping colours) reports themes: null + themes_note --
    # never themes: [] -- because the mate detectors are hard-coded to the
    # black king and can't run safely on the flipped position. If explorer.js
    # ever regresses to `themesEl.textContent = themeSummary(body.themes);`
    # (dropping the `themes_note ||` fallback), themeSummary(null) returns ""
    # and every flipped position would render nothing... except mine.js's
    # theme picker is unaffected, so this specific regression is silent in
    # every other test. Assert the actual flip explanation, not just
    # "non-empty".
    flipped_fen = "6q1/8/8/8/8/5k2/7K/8 w - - 0 1"
    page.goto(f"{server}/#fen={quote(flipped_fen)}")
    page.wait_for_function(
        "() => document.getElementById('position-themes').textContent.length > 0")
    text = page.inner_text("#position-themes")
    assert "flip" in text.lower()
    assert text != "no themes detected"


SATURATED = "8/8/7k/8/8/8/8/KQ6 b - - 0 1"
THREE_GROUPS = "7k/8/5K2/8/8/8/8/6Q1 w - - 0 1"


def _rows(page, selector="#move-list li"):
    return page.eval_on_selector_all(selector, "els => els.map(e => e.dataset.san)")


def _nav_panels(page):
    """The screens the header offers, in order.

    Named, not counted. These assertions used to be `count() == 4`, and adding
    the About screen broke four tests that had nothing to do with About --
    each reporting `assert 5 == 4`, which says nothing about which screen
    appeared. The thing under test is whether SEARCH is on the nav, so the
    assertion should name search.
    """
    return page.eval_on_selector_all(
        "nav[aria-label='Screens'] button", "els => els.map(e => e.dataset.panel)")


# Every screen a default (search-off) server offers. Search is the only one
# whose presence depends on how the server was started, so the two constants
# differ by exactly that one entry.
NAV_WITHOUT_SEARCH = ["explorer", "puzzles", "materials", "themes", "about"]
NAV_WITH_SEARCH = ["explorer", "puzzles", "materials", "mine", "themes", "about"]


def _sticky_is_wired(page):
    """Structural proof that `.board-pin` CAN stick, independent of how much
    scroll room actually exists on the current position.

    Before the chip pass, the Slower group's 25 full rows made `.side` far
    taller than `.board-col`'s own ~700px of content, and `.rail`/
    `.board-col` stretches to match the taller of the two (see the Fix
    round 1 comment on `.board-pin` in app.css) -- so a long move list gave
    the sticky element roughly 2000px of travel room, comfortably more than
    a fixed 400/600px test scroll. Task 4 collapsed that same group to a
    handful of chip rows, and the travel room a sticky element gets is
    `containing-block content height - element's own height`, not the
    padding either side of it: verified live on THREE_GROUPS post-chips,
    scrolling every 2px from 70 to 128 moved `.board-pin`'s top by exactly
    -2px each step with no plateau anywhere -- the two are now equal in
    height (`.board-col` -- not `.side` -- is the taller natural item, so
    the row is sized to IT, and `.board-pin` already fills its container's
    content box with zero slack). That is a structural consequence of a
    short move list, not a bug: once `.side` is no longer taller than the
    board column, there is nothing left for `.board-pin` to travel through,
    on ANY position, not just this one. A scroll-and-measure assertion can
    no longer tell "sticky is wired correctly" apart from "there happens to
    be no room to prove it either way", so this checks the two structural
    preconditions for sticking instead: the computed position is `sticky`
    (not `static`, e.g. from a deleted rule), and no ancestor between it and
    the document root clips or scrolls (`overflow` other than `visible`
    anywhere in the chain silently kills stickiness -- see the caller's own
    comment).
    """
    return page.evaluate("""() => {
      const pin = document.querySelector('.board-pin');
      if (getComputedStyle(pin).position !== 'sticky') return { ok: false, why: 'position is not sticky' };
      for (let el = pin.parentElement; el; el = el.parentElement) {
        const ov = getComputedStyle(el).overflow;
        if (ov !== 'visible') {
          return { ok: false, why: `${el.tagName}.${el.className} has overflow: ${ov}` };
        }
      }
      return { ok: true, why: null };
    }""")


def test_optimal_moves_are_ordered_by_ascending_child_count(page, server):
    # Landing position: Kh6 has 3 optimal continuations, Kh8 has 1, and the
    # move generator emits them in that (wrong) order. Kh8 is the more forcing
    # move and must lead. Measured against KQvk on 2026-08-11.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert _rows(page, "#move-list section[data-group=optimal] li") == ["Kh8", "Kh6"]


def test_a_saturated_child_count_renders_as_a_ceiling_not_a_number(page, server):
    # 8/8/7k/8/8/8/8/KQ6 b: Kg5 leads to a child whose count has saturated at
    # 255, Kh5 to one with 246. The saturated move must sort last (255 > 246)
    # and must never claim "255 ways" -- a ceiling is not a measurement.
    page.goto(f"{server}/#fen={quote(SATURATED)}")
    page.wait_for_selector("#move-list li")
    optimal = "#move-list section[data-group=optimal] li"
    assert _rows(page, optimal) == ["Kh5", "Kg5"]
    badges = page.eval_on_selector_all(
        f"{optimal} .badge", "els => els.map(e => e.textContent)")
    # The optimal group's badge no longer repeats the h#N distance -- every
    # optimal move sits at the same distance, and #position-summary (checked
    # below) already states it once.
    assert badges == ["246 ways", "255+ ways"]
    # The position's OWN count also saturates here (it is the sum of its
    # optimal children's counts, capped at the same ceiling) -- the summary
    # line above the badges must honour the same rule they do: a ceiling is
    # never a measurement. Measured against KQvk on 2026-08-11: this position
    # is dtm=10 (h#5), count=255.
    summary = page.inner_text("#position-summary")
    assert summary == "dtm 10 (h#5) · 255+ optimal lines"
    assert "255 optimal line" not in summary


def test_all_three_groups_render_in_order_with_counted_headers(page, server):
    # 7k/8/5K2/8/8/8/8/6Q1 w -- the position after Kh8. 28 legal moves:
    # one optimal (Qg7#), 25 slower, 2 that lead nowhere.
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    groups = page.eval_on_selector_all(
        "#move-list section.move-group", "els => els.map(e => e.dataset.group)")
    assert groups == ["optimal", "slower", "dead"]

    headers = page.eval_on_selector_all(
        "#move-list section.move-group h3", "els => els.map(e => e.textContent)")
    assert headers == ["Optimal 1", "Slower 25", "No mate 2"]

    # Row one is the answer, whatever the generator emitted.
    assert _rows(page)[0] == "Qg7#"
    assert page.eval_on_selector(
        "#move-list li .badge", "e => e.textContent") == "only reply"

    # The slower group is ordered by mate length first, then by count.
    assert _rows(page, "#move-list section[data-group=slower] li")[:6] == [
        "Qa7", "Qg2", "Qg3", "Qg4", "Qg5", "Kf7"]
    assert _rows(page, "#move-list section[data-group=dead] li") == ["Qg6", "Qg8+"]


def test_the_group_header_is_not_a_move_row(page, server):
    # The whole DOM contract in one assertion: three headers exist, and
    # `#move-list li` still counts exactly the 28 moves and nothing else.
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector_all("#move-list section.move-group h3",
                                     "els => els.length") == 3
    sans = _rows(page)
    assert len(sans) == 28
    assert all(sans), "every #move-list li must carry a data-san"


def test_a_mate_position_renders_prose_not_a_miscounted_move_row(page, server):
    # explorer.js's renderMoveList has a comment explaining why the empty
    # branch renders a <p class="empty"> rather than an <li>: seven other
    # tests in this file use `#move-list li` as their "the page is ready"
    # idiom, and two of them count it -- an <li> here would be silently
    # counted as a move. Nothing reached this branch until now: reverting the
    # <p> back to an <li> passes every other gate in this suite.
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    page.click("#move-list li[data-san='Qg7#']")   # h#0: mate, no legal replies
    page.wait_for_selector("#move-list .empty")
    assert page.eval_on_selector_all("#move-list li", "els => els.length") == 0
    assert page.is_visible("#move-list .empty")


def test_slower_moves_render_as_chips_under_a_distance_band(page, server):
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    labels = page.eval_on_selector_all(
        "#move-list section[data-group=slower] .band-label",
        "els => els.map(e => e.textContent.trim())")
    assert labels and all(lbl.startswith("h#") for lbl in labels), labels
    # the chips carry no badge -- the band label already said it
    assert page.eval_on_selector_all(
        "#move-list section[data-group=slower] .badge", "e => e.length") == 0
    # and the optimal group still does
    assert page.eval_on_selector_all(
        "#move-list section[data-group=optimal] .badge", "e => e.length") > 0


def test_the_no_mate_bands_label_cell_is_empty_not_omitted(page, server):
    # The no-mate group's band() returns a null label. .band is a two-column
    # grid (label, chips); if the (empty) label span were omitted instead of
    # rendered empty, the <ul class="chips"> would become the grid's FIRST
    # child and land in the 3.2rem label column instead of the 1fr chip
    # column -- narrow enough that every chip wraps onto its own row. Proven
    # to bite: reverting renderGroup's unconditional `wrap.appendChild(lab)`
    # back to `if (band.label) wrap.appendChild(lab)` fails this test (Qg6
    # and Qg8+ land at different `top`s instead of sharing a row).
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list section[data-group=dead] li")
    tops = page.eval_on_selector_all(
        "#move-list section[data-group=dead] .chips li",
        "els => els.map(e => e.getBoundingClientRect().top)")
    assert len(tops) == 2, tops   # Qg6, Qg8+ -- both dead moves on THREE_GROUPS
    assert tops[0] == tops[1], f"the dead group's chips did not share a row: {tops}"


def test_every_legal_move_is_still_one_list_item(page, server):
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    shown = page.eval_on_selector_all("#move-list li", "els => els.length")
    api = page.evaluate("""async () => {
      const fen = document.getElementById('fen-input').value;
      const r = await fetch('/v1/moves?fen=' + encodeURIComponent(fen));
      return (await r.json()).moves.length;
    }""")
    assert shown == api, f"{shown} rendered vs {api} legal moves"


def test_a_chip_plays_its_move(page, server):
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list section[data-group=slower] li")
    before = page.input_value("#fen-input")
    page.click("#move-list section[data-group=slower] li")
    page.wait_for_function("b => document.getElementById('fen-input').value !== b", arg=before)


def test_playing_a_move_never_collapses_the_move_list(page, server):
    # render() used to empty the move list synchronously before awaiting the
    # fetch that refills it, so everything below the list jumped up ~286px
    # for the ~22ms the fetch was in flight. Measured live on this fixture
    # (2026-08-13). Poll the list's rendered height across a couple of
    # animation frames after the click and require it never touches zero.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    trace = page.evaluate("""() => new Promise(res => {
      const H = () => Math.round(document.getElementById('move-list').getBoundingClientRect().height);
      const seen = [];
      const t0 = performance.now();
      const tick = () => { seen.push(H());
        if (performance.now() - t0 < 1200) requestAnimationFrame(tick); else res(seen); };
      document.querySelector('#move-list section[data-group=optimal] li').click();
      tick();
    })""")
    assert min(trace) > 0, f"the move list collapsed to zero during the move: {trace[:8]}"


def test_the_board_stays_put_while_the_answer_scrolls(page, server):
    # Syzygy's structural win, without its 310px cap: a long move list must
    # never drag the board off screen. No sticky headers, no scroll sync --
    # position: sticky on .board-pin, and only above the breakpoint.
    # Fix round 1: sticky moved off .board-col (the rail, which fix round 1
    # stretches to the readout's full height so its background covers the
    # whole column -- see the C2 comment in app.css) onto .board-pin, the
    # inner wrapper around #board and .palette that is still only as tall as
    # its own content. So this now asserts on .board-pin, not .board-col.
    #
    # Task 4: this used to scroll by a fixed 600px and assert the pin held
    # near the top -- reliable back when the Slower group's 25 full rows
    # made .side (and so the stretched .board-col/.rail containing it) far
    # taller than the board, giving roughly 2000px of travel room. Chips
    # collapsed that margin to zero on THREE_GROUPS (see _sticky_is_wired's
    # docstring for the live measurement), so a scroll-and-measure assertion
    # can no longer distinguish "sticky is wired" from "there is nothing to
    # prove it with either way" on this position. Assert the structural
    # preconditions instead.
    page.set_viewport_size({"width": 1280, "height": 700})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    wired = _sticky_is_wired(page)
    assert wired["ok"], wired["why"]
    # Above the breakpoint #panel-explorer is a grid. grid-template-columns
    # computes to "none" when the element is not a grid and to resolved track
    # sizes when it is, so this pins the media query itself rather than a side
    # effect that a flex-wrap layout could also produce.
    assert page.evaluate(
        "getComputedStyle(document.getElementById('panel-explorer')).gridTemplateColumns"
    ) != "none"


def test_below_the_breakpoint_the_columns_stack_and_nothing_is_hidden(page, server):
    page.set_viewport_size({"width": 420, "height": 900})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector(".board-col", "e => e.getBoundingClientRect()")
    side = page.eval_on_selector(".side", "e => e.getBoundingClientRect()")
    assert side["top"] >= board["bottom"] - 1, "columns did not stack"
    # Nothing is hidden on a small screen -- hiding controls is a support burden.
    for sel in ("#tray-white", "#fen-form", "#move-list", "#btn-export-pgn"):
        assert page.is_visible(sel), f"{sel} disappeared at 420px"
    # And the page never scrolls sideways.
    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    # ...and below it, the grid must not apply at all.
    assert page.evaluate(
        "getComputedStyle(document.getElementById('panel-explorer')).gridTemplateColumns"
    ) == "none"


def test_reference_material_appears_only_on_the_landing_position(page, server):
    # The benchmark renders its About/Download copy only when the FEN is the
    # default: ask a real question and the explanatory copy vanishes. A
    # published tool explains itself to a newcomer, then gets out of the way.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.is_visible("#primer")
    assert page.is_visible("#explorer-help")

    page.goto(f"{server}/#fen={quote(SATURATED)}")
    page.wait_for_selector("#move-list li")
    page.wait_for_function("() => document.getElementById('primer').hidden === true")
    assert not page.is_visible("#explorer-help")


def test_there_is_no_colour_theme_control_and_no_theme_attribute(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector_all("#theme-toggle", "e => e.length") == 0
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None


def test_the_title_is_the_most_prominent_text_in_the_header(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    title = page.eval_on_selector("header h1", "e => parseFloat(getComputedStyle(e).fontSize)")
    tagline = page.eval_on_selector(".tagline", "e => parseFloat(getComputedStyle(e).fontSize)")
    nav = page.eval_on_selector("nav button", "e => parseFloat(getComputedStyle(e).fontSize)")
    assert title >= tagline * 1.6, f"title {title}px vs tagline {tagline}px"
    assert title > nav, f"title {title}px vs nav {nav}px"


def test_every_footer_link_points_somewhere_real(page, server):
    """The footer used to carry three href-less placeholders. They are now
    real links, so the property worth asserting flipped: nothing in the footer
    may be a placeholder any more, and nothing may be a bare `#`.

    `href="#"` is the specific trap this guards (see
    test_a_footer_link_keeps_the_position_it_was_clicked_from below): it
    CLEARS location.hash, which panels.js reads as "explorer".
    """
    page.goto(server)
    page.wait_for_selector("footer")
    assert page.is_visible("footer")
    links = page.eval_on_selector_all(
        "footer nav a",
        "els => els.map(e => ({text: e.textContent.trim(),"
        " href: e.getAttribute('href'), placeholder: e.hasAttribute('data-placeholder')}))")
    assert len(links) >= 3, f"footer has only {len(links)} links"
    for a in links:
        assert not a["placeholder"], f"{a['text']} still marked as a placeholder"
        assert a["href"], f"{a['text']} has no href"
        assert a["href"] != "#", f"{a['text']} is a bare '#'"
        assert a["href"].startswith(("https://", "#panel=")), a
    # Dataset is deliberately NOT here: the tables are unpublished, and the
    # About screen says so in a sentence rather than shipping a 404.
    assert [a["text"] for a in links] == ["Source", "Licence", "About", "Privacy"]


def test_the_drag_ghost_has_no_background_and_is_smaller_than_the_tray(page, server):
    page.goto(server)
    page.wait_for_selector("#tray-white button")
    box = page.locator("#tray-white button[data-piece=wq]").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 120, box["y"] - 60, steps=6)
    ghost = page.eval_on_selector(".drag-ghost", """e => {
      const s = getComputedStyle(e);
      return {bg: s.backgroundColor, border: s.borderTopWidth,
              w: e.getBoundingClientRect().width};
    }""")
    page.mouse.up()
    assert ghost["bg"] in ("rgba(0, 0, 0, 0)", "transparent"), ghost["bg"]
    assert ghost["border"] == "0px", ghost["border"]
    assert ghost["w"] < box["width"], f"ghost {ghost['w']} >= tray {box['width']}"


def test_search_results_are_numbered_and_open_in_the_explorer(page, server_mining):
    page.goto(f"{server_mining}/#panel=mine")
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#mine-results li")
    idx = page.eval_on_selector_all("#mine-results li .idx",
                                    "els => els.map(e => e.textContent)")
    assert idx == [str(n) for n in range(1, len(idx) + 1)]
    assert len(idx) == page.eval_on_selector_all("#mine-results li", "els => els.length")
    # each row still carries its FEN and still navigates
    first = page.eval_on_selector("#mine-results li .fen", "e => e.textContent")
    assert first.count("/") == 7
    page.click("#mine-results li")
    page.wait_for_selector("#panel-explorer:not([hidden])")
    # The click sets location.hash; panels.js and explorer.js both react to
    # hashchange, and explorer's render() is async -- so wait for the value
    # rather than reading it in the same tick.
    page.wait_for_function(
        "want => document.getElementById('fen-input').value === want", arg=first)


def test_a_material_with_no_helpmate_says_so(page, server):
    # KBvk: king and bishop cannot mate. The sidecar stores max_dtm = 255,
    # the DTM_UNSOLVABLE sentinel; dividing it by two rendered "h#127.5" for
    # 67 of the 295 tables in the reference corpus.
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    page.click("#material-list li[data-material=Kvk]")
    page.wait_for_selector("#material-stats .stats-head")
    sub = page.inner_text("#material-stats .stats-head")
    assert "no helpmate exists" in sub
    assert "127.5" not in sub
    assert "h#" not in sub.split("·")[0]


@pytest.mark.parametrize("width", [880, 960, 1024, 1280])
def test_the_board_never_overlaps_the_readout(page, server, width):
    # Regression, measured before the fix: #board was min(88vw, 460px) while
    # its grid column was min(460px, 40%). At 960px that put a 460px board in
    # a 368px column, 66px of it lying on top of the move list.
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    side = page.eval_on_selector(".side", "e => e.getBoundingClientRect()")
    assert board["right"] <= side["left"] + 1, (
        f"board overlaps the readout by {board['right'] - side['left']:.0f}px at {width}px")


@pytest.mark.parametrize("width", [880, 1280])
def test_the_board_is_centred_in_its_rail(page, server, width):
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    rail = page.eval_on_selector(".board-col", "e => e.getBoundingClientRect()")
    left = board["left"] - rail["left"]
    right = rail["right"] - board["right"]
    assert abs(left - right) <= 1, f"board off-centre by {abs(left - right):.1f}px"


def test_the_rail_and_the_readout_are_different_surfaces(page, server):
    page.set_viewport_size({"width": 1280, "height": 1000})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    rail = page.eval_on_selector(".board-col", "e => getComputedStyle(e).backgroundColor")
    readout = page.eval_on_selector(".side", "e => getComputedStyle(e).backgroundColor")
    assert rail != readout, "rail and readout render on the same surface"
    assert rail not in ("rgba(0, 0, 0, 0)", "transparent")
    assert readout not in ("rgba(0, 0, 0, 0)", "transparent")


def test_the_board_stays_put_while_the_readout_scrolls(page, server):
    # .board-pin (wrapping #board and .palette) is sticky. `overflow: hidden`
    # on any ancestor would create a scroll container and silently kill that
    # -- an easy thing to add while clipping surfaces to a border radius, and
    # invisible to every other test.
    #
    # Task 4: this used to scroll by a fixed 400px and assert #board's top
    # moved by less than the raw scroll (sticking) and stayed on screen.
    # Measured live (2026-08-13, fine 4px scan of scrollY 0..200 on this
    # exact fen/viewport): .board-pin's top decreases in EXACT lockstep with
    # scrollY the entire way -- no plateau anywhere -- because collapsing the
    # Slower group to chips removed .board-pin's containing block's entire
    # travel room on THREE_GROUPS (see _sticky_is_wired's docstring). There
    # is no scroll amount, fixed or computed, that lands #board near the top:
    # scrolling by 400px (the old fixed amount) puts it at top=-222.6, and
    # the same monotonic slope holds at every point tried. A scroll-and-
    # measure assertion cannot distinguish "sticky is wired" from "there is
    # nothing to prove it with either way" on this position -- the same
    # finding the sibling test
    # (test_the_board_stays_put_while_the_answer_scrolls) already acted on.
    # Assert the structural preconditions instead, via the same helper.
    page.set_viewport_size({"width": 1280, "height": 700})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    wired = _sticky_is_wired(page)
    assert wired["ok"], wired["why"]
    # #board sits inside .board-pin at a fixed internal offset that scrolling
    # must never disturb, independent of whether the pin itself has room to
    # stick on this particular position -- if this ever moves, #board and
    # .board-pin have come apart (e.g. #board gained its own margin/position)
    # even though the pin's own sticky wiring is untouched.
    offset = page.evaluate("""() => {
      const pin = document.querySelector('.board-pin');
      const board = document.getElementById('board');
      return board.getBoundingClientRect().top - pin.getBoundingClientRect().top;
    }""")
    page.evaluate("window.scrollBy(0, 400)")
    page.wait_for_timeout(100)
    offset_after = page.evaluate("""() => {
      const pin = document.querySelector('.board-pin');
      const board = document.getElementById('board');
      return board.getBoundingClientRect().top - pin.getBoundingClientRect().top;
    }""")
    assert abs(offset_after - offset) < 1, (
        "#board's offset inside .board-pin shifted while scrolling "
        f"({offset} -> {offset_after})")


def test_the_board_actually_sticks_when_the_page_scrolls(page, server):
    # M5. The earlier structural-only checks passed even with `top` removed,
    # which disables sticky entirely. .board-col's own height minus
    # .board-pin's height leaves ~101.7px of slack on the landing position at
    # 900px, so sticky is doing real work here and this can assert the real
    # behaviour rather than the CSS declaration.
    #
    # That slack is room at the BOTTOM of the sticky range, not the amount of
    # scroll needed to REACH it -- a distinction the review's own first draft
    # of this test missed (scrolling by a bare 100px and expecting the pin to
    # have mostly stopped moving already). Measured live on this fixture
    # (2026-08-13, 900x700): .rail's 16px padding-top plus the header/nav
    # above .board-col put the pin's resting top at ~154px, so the page must
    # scroll ~138px before the pin reaches the sticky offset (var(--s3),
    # 16px) at all; below that it tracks the scroll 1:1, which is correct,
    # not broken. The stuck plateau (top pinned at exactly 16px) runs from
    # scroll≈138 to scroll≈205 before .board-col's bottom edge starts pushing
    # the pin off again. Scroll well inside that plateau -- with margin on
    # both sides so this cannot flake on the boundary -- and prove the pin
    # has actually stopped moving across a further scroll delta, which no
    # amount of scrolling below the engagement point could show.
    page.set_viewport_size({"width": 900, "height": 700})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.evaluate("window.scrollBy(0, 170)")
    page.wait_for_timeout(120)
    mid = page.eval_on_selector(".board-pin", "e => e.getBoundingClientRect().top")
    page.evaluate("window.scrollBy(0, 25)")
    page.wait_for_timeout(120)
    after = page.eval_on_selector(".board-pin", "e => e.getBoundingClientRect().top")
    assert abs(after - mid) < 1, (
        f"the pin kept moving with the page ({mid:.1f} -> {after:.1f}); sticky is inert")


def test_the_explorer_shows_the_table_this_position_came_from(page, server):
    page.goto(server)
    page.wait_for_selector("#table-stats .table-line")
    assert "KQvk" in page.inner_text("#table-stats .table-line")
    # the band is a one-line summary, not a second copy of Materials' charts --
    # those live one click away, via #btn-open-material
    assert page.eval_on_selector_all("#table-stats .hist", "e => e.length") == 0
    assert page.eval_on_selector_all("#table-stats .tiles", "e => e.length") == 0


def test_the_table_band_refetches_only_when_the_material_actually_changes(page, server):
    # A single-table fixture can never distinguish "correctly cached" from
    # "never refetches at all" using only same-material moves -- KQvk -> KQvk
    # moves prove nothing about the fetch-when-changed branch of the
    # bandMaterial === material guard. Kxg1 is a real material transition
    # reachable inside this very fixture: KQvk's own closure already
    # generates a Kvk table too (see
    # test_materials_panel_lists_tables_and_opens_a_sample), and capturing
    # White's queen leaves exactly that material on the board. Verified with
    # python-chess: from "K7/8/8/8/8/8/6k1/6Q1 b - - 0 1" (White Ka8+Qg1,
    # Black kg2, Black to move) Kxg1 is a legal king move and lands on
    # "K7/8/8/8/8/8/8/6k1 w - - 0 1", queried against the fixture on
    # 2026-08-12: material "KQvk" before, "Kvk" after.
    capture_fen = "K7/8/8/8/8/8/6k1/6Q1 b - - 0 1"
    page.goto(f"{server}/#fen={quote(capture_fen)}")
    page.wait_for_selector("#table-stats .table-line")
    assert "KQvk" in page.inner_text("#table-stats .table-line")

    # Match /v1/materials/<name>/stats only. A bare "/stats" would also match
    # the corpus aggregate, which initMaterials() requests on load -- an async
    # call that can land after this patch and turn the test flaky.
    page.evaluate("""() => {
      window.__statsCalls = [];
      const orig = window.fetch;
      window.fetch = (...a) => {
        const m = String(a[0]).match(/\\/v1\\/materials\\/([^/]+)\\/stats/);
        if (m) window.__statsCalls.push(m[1]);
        return orig(...a);
      };
    }""")

    # Kh3 keeps the same material (KQvk): the guard's early-return branch,
    # zero further fetches.
    page.click("#move-list li[data-san='Kh3']")
    page.wait_for_function(
        "document.getElementById('position-summary').textContent.includes('dtm')")
    assert page.evaluate("window.__statsCalls") == [], "refetched a material that didn't change"

    page.click("#btn-back")
    page.wait_for_function(
        "want => document.getElementById('fen-input').value === want", arg=capture_fen)

    # Kxg1 changes the material (KQvk -> Kvk): the guard's fetch branch,
    # exactly one new request, for the new material.
    page.click("#move-list li[data-san='Kxg1']")
    page.wait_for_function(
        "document.getElementById('table-stats').dataset.material === 'Kvk'")
    assert page.evaluate("window.__statsCalls") == ["Kvk"], "did not refetch for the changed material"


def test_the_table_band_opens_the_material(page, server):
    page.goto(server)
    page.wait_for_selector("#table-stats .table-line")
    page.click("#btn-open-material")
    page.wait_for_selector("#panel-materials:not([hidden])")
    assert page.get_attribute(
        "#material-list li[data-material=KQvk]", "aria-selected") == "true"


def test_the_rail_matches_the_readout_height_on_a_tall_move_list(page, server):
    # Fix round 1 / C2 regression: #panel-explorer is a grid with
    # `align-items: start` (pre-fix), so .rail/.board-col sized itself to its
    # own short content (board + palette) while the grid row's height
    # followed the taller .readout. Below the rail's content, the ancestor
    # panel's --readout background showed straight through -- a hard colour
    # seam, invisible on the landing position (whose short move list makes
    # the two columns nearly equal height) but covering most of the card on
    # THREE_GROUPS's 28-move list. The rail must now stretch to match.
    page.set_viewport_size({"width": 1280, "height": 1100})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    rail = page.eval_on_selector(".board-col", "e => e.getBoundingClientRect()")
    readout = page.eval_on_selector(".side", "e => e.getBoundingClientRect()")
    assert abs(rail["bottom"] - readout["bottom"]) <= 2, (
        f"rail bottom {rail['bottom']:.1f} != readout bottom {readout['bottom']:.1f}")


def test_materials_lands_on_the_corpus_summary(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    page.wait_for_selector("#material-stats .stats-head")
    head = page.inner_text("#material-stats .stats-head")
    assert "All tables" in head
    assert page.get_attribute("#material-list li[data-material='*']", "aria-selected") == "true"
    assert page.eval_on_selector_all("#agg-dtm-hist", "e => e.length") == 1
    # the corpus's uncomfortable facts are stated, not dropped
    assert page.is_visible("#agg-no-helpmate")


def test_the_material_rail_filters(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    all_names = page.eval_on_selector_all(
        "#material-list li[data-material]:not([hidden])", "els => els.length")
    page.fill("#material-filter", "kqv")
    page.wait_for_function(
        "document.querySelectorAll('#material-list li[data-material]:not([hidden])').length < %d"
        % all_names)
    shown = page.eval_on_selector_all(
        "#material-list li[data-material]:not([hidden])",
        "els => els.map(e => e.dataset.material)")
    assert shown, "the filter hid everything"
    # "*" (the pinned "All tables" entry) is deliberately never filtered
    # away -- it is the way back -- so it is excluded from the substring
    # check below and asserted separately instead.
    assert all("kqv" in m.lower() for m in shown if m != "*")
    assert page.is_visible("#material-list li[data-material='*']")


def test_the_material_rail_scrolls_instead_of_the_page(page, server):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    overflow = page.eval_on_selector("#material-list", "e => getComputedStyle(e).overflowY")
    assert overflow in ("auto", "scroll")
    height = page.evaluate("document.documentElement.scrollHeight")
    assert height < 4000, f"page is {height}px tall; the rail is not containing the list"


def test_the_rail_groups_by_piece_count(page, server):
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    heads = page.eval_on_selector_all("#material-list li.group", "els => els.map(e => e.textContent)")
    assert any("PIECES" in h.upper() for h in heads)


def test_the_materials_rail_matches_the_readout_height(page, server):
    # Review fix round 1: #panel-materials is a grid. With `align-items:
    # start` (pre-fix) .rail/.list-col sized itself to its own short content
    # (heading + filter + list) while the grid row's height followed the
    # taller .readout -- the "All tables" summary, with its histograms and
    # name lists, is reliably taller than a materials list short enough to
    # fit the fixture's two tables. Below the rail's content the ancestor
    # panel's --readout background showed through where --rail was expected:
    # the wrong surface colour, not an unpainted gap, which is exactly why a
    # full-page screenshot missed it (both are painted; only the token
    # differs). Assert equality, not "at least as tall" -- with the default
    # `align-items: stretch` this holds by construction regardless of how
    # many materials the corpus has, so it does not depend on generating
    # enough rows to out-grow the readout the way the explorer's analogous
    # test drives a long move list.
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    page.wait_for_selector("#material-stats .stats-head")
    rail = page.eval_on_selector(".list-col", "e => e.getBoundingClientRect()")
    readout = page.eval_on_selector(".detail-col", "e => e.getBoundingClientRect()")
    assert abs(rail["bottom"] - readout["bottom"]) <= 2, (
        f"rail bottom {rail['bottom']:.1f} != readout bottom {readout['bottom']:.1f}")


def test_a_timed_out_search_says_so_instead_of_reporting_no_results(page, server_mining):
    # The server answers a timeout with {fens: [], truncated: true,
    # note: "timeout"}. Rendering that as "0 position(s) (truncated -- raise
    # max results for more)" is advice that cannot help, about a result that
    # was never computed.
    page.goto(f"{server_mining}/#panel=mine")
    page.route("**/v1/mine**", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"fens": [], "truncated": true, "note": "timeout", "skipped_saturated": 0}'))
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.toLowerCase().includes('timed out')")
    status = page.inner_text("#mine-status")
    assert "raise max results" not in status
    assert "0 position(s)" not in status


def test_the_search_button_becomes_stop_while_in_flight(page, server_mining):
    page.goto(f"{server_mining}/#panel=mine")
    page.route("**/v1/mine**", lambda route: None)   # never respond
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#btn-stop:not([hidden])")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('of ')")
    page.click("#btn-stop")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.toLowerCase().includes('stopped')")
    assert page.is_hidden("#btn-stop")
    assert page.is_visible("#mine-form button[type=submit]")


def test_the_countdown_uses_the_servers_budget(page, server_mining):
    # The fixture server's default mine_timeout (30) is the same number as
    # mine.js's hardcoded fallback, so asserting "of 30s" against the real
    # /v1/health response would pass identically whether the health call
    # ever happened or not. Mock a different budget so the test can only
    # pass if the countdown actually reads it from the server.
    page.route("**/v1/health**", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"status": "ok", "version": "0.0.0", "mine_timeout": 7, '
             '"tables_local": 1, "tables_remote": 0, "mining_enabled": true}'))
    page.goto(f"{server_mining}/#panel=mine")
    page.route("**/v1/mine**", lambda route: None)
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('of 7s')")


def test_pressing_enter_mid_search_does_not_orphan_the_ticker(page, server_mining):
    # Fix round 1 (code review): setBusy(true) only sets `hidden` on the
    # submit button, which does not stop Enter-key implicit form submission
    # -- so a second /v1/mine can fire while the first is still in flight,
    # even though the Search button is invisible. Before the guard, that
    # second submission's startTicker() call overwrote the module-level
    # `ticker` variable, orphaning the first interval: pressing Stop then
    # correctly showed "Stopped..." for one tick, and the orphaned interval
    # (still ticking against the FIRST search's own `began` timestamp) kept
    # overwriting #mine-status with "searching... Ns of 30s" every second
    # after that, forever -- the honest timeout message silently reverting
    # to a stale "searching..." line. Reproduces the reviewer's exact
    # sequence: click Search, submit again via Enter (not a second click),
    # press Stop, then wait past a full tick and confirm the Stopped message
    # held.
    page.goto(f"{server_mining}/#panel=mine")
    page.route("**/v1/mine**", lambda route: None)   # never respond
    material = page.locator("#mine-form input[name=material]")
    material.fill("KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#btn-stop:not([hidden])")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('of ')")
    # Implicit submission via Enter in a text field, while the first search
    # is still in flight and its Search button is only `hidden`, not
    # disabled -- the reachable path the reviewer identified.
    material.press("Enter")
    page.click("#btn-stop")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.toLowerCase().includes('stopped')")
    page.wait_for_timeout(3000)   # past a full orphaned-ticker tick, if one exists
    status = page.inner_text("#mine-status")
    assert "stopped" in status.lower(), status
    assert "searching" not in status.lower(), status


def test_stop_and_the_busy_state_survive_a_downloading_retry(page, server_mining):
    # Fix round 1 (code review): the 202 branch used to schedule its retry
    # with a bare setTimeout and return immediately, so the submit handler's
    # `finally` unwound as soon as the FIRST 202 arrived -- Stop hidden,
    # Search shown, ticker stopped, inFlight nulled -- while the status
    # still read "downloading...". With inFlight null, the retry's own
    # api.mine call read `signal: undefined`, making the retry loop
    # unabortable. Confirm Stop (and the busy state generally) survives
    # across a 202 -> 200 retry.
    calls = {"n": 0}

    def handle_mine(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=202, content_type="application/json",
                           body='{"material": "KQvk"}')
        else:
            route.fulfill(status=200, content_type="application/json",
                           body='{"fens": [], "truncated": false, "skipped_saturated": 0}')

    page.goto(f"{server_mining}/#panel=mine")
    page.route("**/v1/mine**", handle_mine)
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('downloading')")
    assert page.is_visible("#btn-stop"), "Stop disappeared while still downloading"
    assert page.is_hidden("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('position(s)')")
    assert calls["n"] >= 2, "the retry never actually fired"
    assert page.is_hidden("#btn-stop")
    assert page.is_visible("#mine-form button[type=submit]")


def test_the_search_rail_matches_the_readout_height(page, server_mining):
    # Same defect class as the explorer's .board-pin and materials'
    # .materials-pin fixes (see the Fix round 1 comment at .board-pin in
    # app.css): #mine-form/.rail must stretch to the grid row's full height
    # while .mine-pin carries the sticky behaviour at its own, shorter
    # height -- or the strip below the form paints --readout instead of
    # --rail once the results list outgrows the form fields. dtm=1 on the
    # KQvk fixture returns 50 rows (measured 2026-08-12), reliably taller
    # than the six-field form.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server_mining}/#panel=mine")
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "1")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#mine-results li")
    rail = page.eval_on_selector("#mine-form", "e => e.getBoundingClientRect()")
    readout = page.eval_on_selector("#panel-mine .readout", "e => e.getBoundingClientRect()")
    assert abs(rail["bottom"] - readout["bottom"]) <= 2, (
        f"rail bottom {rail['bottom']:.1f} != readout bottom {readout['bottom']:.1f}")


def test_search_is_absent_not_hidden_when_mining_is_disabled(page, server):
    """Absence, not display:none. A hidden form still submits on Enter --
    that exact bug shipped once and left a ticker running forever."""
    page.goto(server)
    page.wait_for_function("() => window.__chipReady === true")
    assert _nav_panels(page) == NAV_WITHOUT_SEARCH
    assert page.locator("nav button[data-panel='mine']").count() == 0
    assert page.locator("#panel-mine").count() == 0
    assert page.locator("#mine-form").count() == 0


def test_a_stale_search_deep_link_lands_on_the_explorer(page, server):
    """#panel=mine is a URL people may have bookmarked. With the panel gone it
    must not blank the page -- showPanel would otherwise set .hidden on a null
    and take the whole nav down with it."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/#panel=mine")
    page.wait_for_function("() => window.__chipReady === true")
    assert page.locator("#panel-explorer").is_visible()
    assert errors == []


def test_search_is_present_when_the_server_enables_it(page, server_mining):
    page.goto(server_mining)
    page.wait_for_function("() => window.__chipReady === true")
    assert _nav_panels(page) == NAV_WITH_SEARCH
    assert page.locator("#panel-mine").count() == 1


def test_search_stays_absent_and_the_chip_still_resolves_when_health_is_unreachable(page, server):
    # Fail closed is the other half of index.html's
    # `if (!health || health.mining_enabled !== true)`. Every other test hits
    # a real, answering server, so only the `mining_enabled !== true` half
    # ever ran -- `!health` (and initServerChip(null)'s "server unreachable"
    # branch) was never exercised anywhere. Abort /v1/health outright so the
    # boot's own request throws: the panel must still come out, and the boot
    # must still finish (not hang) and report the chip as unreachable rather
    # than silently leaving `mining_enabled` truthy from a stale default.
    page.route("**/v1/health**", lambda route: route.abort())
    page.goto(server)
    page.wait_for_function("() => window.__chipReady === true")
    assert _nav_panels(page) == NAV_WITHOUT_SEARCH
    assert page.locator("#panel-mine").count() == 0
    assert "unreachable" in page.inner_text("#server-chip")


def test_boot_does_not_hang_when_health_is_slow(page, server):
    # I1: before this branch's boot-time health check gained a timeout, a
    # route that never answers left the top-level `await api.health()` gating
    # every init*() call forever -- an inert shell (no move list, no board,
    # chip never ready). Route /v1/health to hang (never fulfil/abort/
    # continue) rather than fail fast, and confirm the boot still completes:
    # the fail-closed behaviour from the test above, but reached via a
    # timeout instead of a network error. The wait below (10s) is comfortably
    # longer than the 5s deadline api.health() now passes as
    # AbortSignal.timeout(...) (index.html), so a regression back to an
    # unbounded await would time out this wait_for_function, not merely take
    # a little longer.
    page.route("**/v1/health**", lambda route: None)
    page.goto(server)
    page.wait_for_function("() => window.__chipReady === true", timeout=10000)
    assert _nav_panels(page) == NAV_WITHOUT_SEARCH
    assert page.locator("#panel-mine").count() == 0
    assert "unreachable" in page.inner_text("#server-chip")
    # The rest of the boot must have run too, not just the chip/panel-removal
    # decision that shares the same health response.
    page.wait_for_selector("#move-list li")
    assert page.locator("#board svg").count() > 0


def test_dragging_a_piece_from_the_palette_places_it(page, server):
    # Dropping onto h7 overwrites the landing position's black king rather
    # than adding a piece: the fixture only ever generates KPvk, whose
    # closure is KBvk, KNvk, KPvk, KQvk, KRvk, Kvk, so a drop that ADDED a
    # rook alongside the existing queen would land on KQRvk -- a material
    # the fixture never generated -- and 404 instead of ever showing "dtm".
    # Overwriting the king instead exercises kingProblem's no-request short
    # circuit, which answers instantly and deterministically, and still
    # proves the point: the drop evaluates on its own, with nothing clicked
    # first.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    src = page.locator("#tray-white button[data-piece=wr]")
    dst = page.locator("#board rect[data-square=h7]")
    src.drag_to(dst)
    page.wait_for_function(
        "document.getElementById('fen-input').value.split(' ')[0].includes('R')")
    placement = page.input_value("#fen-input").split()[0]
    assert placement.split("/")[1] == "7R", placement
    # a drop evaluates immediately: no arming, no separate Done step
    page.wait_for_function(
        "() => document.getElementById('position-summary').textContent.includes('king')")
    assert page.is_hidden("#error-banner")


def _drag_piece_off_the_board(page, square):
    """Drag whatever is on `square` to a point beside the board, and drop it.

    Right of the board's right edge, at the same y. Straight down (as a naive
    brief once had it) can land below the fixture's 1280x720 viewport, where
    mouse events never dispatch; beside the board stays inside the viewport in
    every layout.
    """
    box = page.locator(f"#board rect[data-square={square}]").bounding_box()
    board_box = page.locator("#board").bounding_box()
    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2
    off_x = board_box["x"] + board_box["width"] + 100   # beside the board, same y
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(off_x, start_y, steps=12)
    page.mouse.up()


def test_dragging_a_piece_off_the_board_removes_it(page, server):
    # The landing position has a white queen on g1. Drag it off the board and
    # it should be gone -- no preparation needed first.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    before = page.input_value("#fen-input")
    assert "Q" in before.split()[0]

    _drag_piece_off_the_board(page, "g1")

    page.wait_for_function(
        "before => document.getElementById('fen-input').value !== before", arg=before)
    assert "Q" not in page.input_value("#fen-input").split()[0]


def test_a_drag_released_on_the_boards_own_bounds_does_not_delete_the_piece(page, server):
    # With `style: { borderType: "frame" }` the widget drew a ~20px
    # coordinate band INSIDE its visible bounds but outside the squares --
    # elementFromPoint at a drop released there hit that border rect, which
    # carries no data-square, and cm-chessboard read that as movedOutOfBoard
    # and deleted the piece, even though the drop looked, to the eye, like it
    # landed on the board. Switching to borderType "none" (inline
    # coordinates, pointer-events: none) removes that band: the squares now
    # tile the board element's full bounds, so any drop inside #board lands
    # on a square. Release right at the board's own top-left corner -- the
    # old frame border's coordinate band used to sit exactly there.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    before = page.input_value("#fen-input")
    assert "Q" in before.split()[0]
    src = _square_box(page, "g1")
    board = page.eval_on_selector("#board", "e => e.getBoundingClientRect()")
    page.mouse.move(src["x"] + src["width"] / 2, src["y"] + src["height"] / 2)
    page.mouse.down()
    page.mouse.move(board["x"] + 1, board["y"] + 1, steps=10)
    page.mouse.up()
    page.wait_for_function(
        "before => document.getElementById('fen-input').value !== before", arg=before)
    assert "Q" in page.input_value("#fen-input").split()[0]


def test_filtering_an_empty_corpus_does_not_throw(page, empty_server):
    # First-run state of a public release: install the server, generate
    # nothing yet, open the dashboard, type in the filter. The list then holds
    # "All tables" plus a "No tables yet" note, and the note carries no
    # data-material -- applyFilter() read .toLowerCase() straight off that
    # undefined, so every keystroke threw an uncaught TypeError and the filter
    # stayed dead for the rest of the session.
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{empty_server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")

    assert page.eval_on_selector_all(
        "#material-list li", "els => els.map(e => e.dataset.material)") == ["*", None]
    assert page.is_visible("#material-list li.empty")

    page.fill("#material-filter", "kq")
    page.fill("#material-filter", "k")
    page.fill("#material-filter", "")

    assert errors == [], errors
    # Both survivors of an empty corpus stay on screen: the way back to the
    # summary, and the note that says why there is nothing else.
    assert page.is_visible("#material-list li[data-material='*']")
    assert page.is_visible("#material-list li.empty")


def test_a_superseded_band_response_does_not_hide_the_current_band(page, server):
    # The band's failure paths (a 202 "still downloading", or an error) used
    # to hide the band unconditionally, without the "is this still MY
    # material?" guard the success path has. So a slow response for a
    # material the user has already navigated away from arrived and blanked
    # the band belonging to the position now on screen -- with nothing to
    # bring it back until the user left the material and came back. The
    # trigger is precisely the remote-chain case this release exists for.
    #
    # KQvk's stats request is held open in the page (not in Playwright's
    # thread) and released by hand after the switch, so this is deterministic
    # rather than a race against a sleep.
    page.add_init_script("""
      window.__releaseStaleStats = null;
      const orig = window.fetch;
      window.fetch = function (input, init) {
        if (String(input).includes("/v1/materials/KQvk/stats")) {
          return new Promise((resolve) => {
            window.__releaseStaleStats = () => resolve(new Response(
              JSON.stringify({status: "fetching", material: "KQvk"}),
              {status: 202, headers: {"content-type": "application/json"}}));
          });
        }
        return orig.call(window, input, init);
      };
    """)
    page.goto(server)                       # the landing position is KQvk
    page.wait_for_selector("#move-list li")
    page.wait_for_function("window.__releaseStaleStats !== null")

    # Move to a Kvk position; its band answers immediately.
    page.fill("#fen-input", "8/8/8/8/8/4k3/8/4K3 w - - 0 1")
    page.press("#fen-input", "Enter")
    page.wait_for_function(
        "document.getElementById('table-stats').dataset.material === 'Kvk'")
    page.wait_for_selector("#table-stats:not([hidden])")

    page.evaluate("window.__releaseStaleStats()")   # the stale 202 lands now
    page.wait_for_timeout(200)

    assert page.eval_on_selector("#table-stats", "e => e.dataset.material") == "Kvk"
    assert page.is_visible("#table-stats"), \
        "a superseded response hid the band of the position on screen"


def test_the_explorer_rail_has_no_rounded_corner_mid_panel(page, server):
    # At the two-column breakpoint every rail rounds its left corners to sit
    # in the panel's own border-radius. In Materials and Mine the rail IS the
    # panel's bottom, so that is right; in the explorer the table band spans
    # both columns underneath it, and the rounded bottom-left corner became a
    # quarter-circle notch of the readout colour in the middle of the panel,
    # directly above the band's square corner.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.wait_for_selector("#table-stats:not([hidden])")

    radii = "e => { const s = getComputedStyle(e); return [s.borderTopLeftRadius, s.borderBottomLeftRadius]; }"
    top, bottom = page.eval_on_selector("#panel-explorer .rail", radii)
    assert top != "0px", "the panel's own top-left corner must stay rounded"
    assert bottom == "0px", f"rounded corner mid-panel: bottom-left is {bottom}"

    # With no band (no material to show stats for) the rail is the panel's
    # bottom again, and the corner has to come back or the rail's square
    # corner overhangs the panel's rounded one.
    page.click("#btn-clear-board")
    page.wait_for_function("document.getElementById('table-stats').hidden === true")
    top2, bottom2 = page.eval_on_selector("#panel-explorer .rail", radii)
    assert bottom2 == top2, f"the rail is the panel's bottom but is not rounded: {bottom2}"


def test_the_explorer_table_band_is_one_line_with_no_histogram(page, server):
    page.goto(server)
    # #table-stats-body is in the static tree and holds "Loading…" while the
    # request is in flight, so waiting on it resolved before the band had any
    # real content -- and the height assertion below then measured the
    # placeholder. Wait for the rendered line itself, the same idiom
    # test_the_explorer_shows_the_table_this_position_came_from uses.
    page.wait_for_selector("#table-stats .table-line")
    assert "KQvk" in page.inner_text("#table-stats")
    # the histograms live on Materials, one click away
    assert page.eval_on_selector_all("#table-stats .hist", "e => e.length") == 0
    assert page.eval_on_selector_all("#table-stats .tiles", "e => e.length") == 0
    h = page.eval_on_selector("#table-stats", "e => e.getBoundingClientRect().height")
    assert h < 120, f"the band is {h:.0f}px tall"


def test_actionable_controls_are_weighted(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    for sel in ("#btn-flip", "#btn-clear-board", "#btn-back", "#btn-export-pgn"):
        w = page.eval_on_selector(sel, "e => getComputedStyle(e).fontWeight")
        assert int(w) >= 600, f"{sel} is weight {w}"
    # inert text is not
    w = page.eval_on_selector("#position-summary", "e => getComputedStyle(e).fontWeight")
    assert int(w) < 600, f"the verdict is weight {w}"


def test_the_themes_screen_explains_every_motif_the_build_detects(page, server):
    page.goto(f"{server}/#panel=themes")
    page.wait_for_selector("#themes-doc .theme-entry")
    names = page.eval_on_selector_all("#themes-doc .theme-entry h3",
                                      "els => els.map(e => e.textContent.trim())")
    api = page.evaluate("""async () => (await (await fetch('/v1/themes')).json())
                             .themes.map(t => t.name)""")
    # Set equality, not a literal list: a motif the build detects but this
    # screen has no named group for must still render (in "other"), so
    # asserting against the live API is the only version of this check that
    # can catch a motif silently dropped.
    assert sorted(names) == sorted(api), f"{len(names)} documented vs {len(api)} detected"
    # every entry says what it reads, because that decides whether it can
    # answer on a saturated position
    needs = page.eval_on_selector_all("#themes-doc .theme-needs", "e => e.length")
    assert needs == len(api)


def test_an_unknown_motif_with_colour_variants_lands_in_other_exactly_once(page, server):
    # The "other" group is this screen's whole reason for existing: a motif
    # the build detects that no hand-written group here names must still
    # appear, with no edit to themes-doc.js. It broke in exactly the shape
    # the registry already ships -- a base motif WITH colour variants.
    # renderGroup snapshotted its member list before the loop and never
    # re-checked it against `placed`, so `pin` correctly nested pin:white and
    # pin:black inside itself and then the snapshot rendered both AGAIN as
    # top-level entries. Task 6a's proof injected a single variant-less motif
    # and could not see it. This one injects the real shape.
    injected = [
        {"name": "pin", "doc": "a made-up motif, for this test only.", "needs": "position"},
        {"name": "pin:white", "doc": "the white-side variant.", "needs": "position"},
        {"name": "pin:black", "doc": "the black-side variant.", "needs": "position"},
    ]

    def with_injection(route):
        body = json.loads(route.fetch().text())
        body["themes"] = body["themes"] + injected
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/v1/themes", with_injection)
    page.goto(f"{server}/#panel=themes")
    page.wait_for_selector("#themes-doc .theme-entry[data-theme=pin]")

    names = page.eval_on_selector_all("#themes-doc .theme-entry h3",
                                      "els => els.map(e => e.textContent.trim())")
    for name in ("pin", "pin:white", "pin:black"):
        assert names.count(name) == 1, f"{name} rendered {names.count(name)} times: {names}"

    # ...and the variants are nested under their base, not siblings of it.
    nested = page.eval_on_selector_all(
        "#themes-doc .theme-entry[data-theme=pin] .theme-variants .theme-entry",
        "els => els.map(e => e.dataset.theme)")
    assert sorted(nested) == ["pin:black", "pin:white"], nested

    # The whole injected set still appears exactly once each overall, so this
    # cannot pass by dropping an entry instead of de-duplicating it.
    api = page.evaluate("""async () => (await (await fetch('/v1/themes')).json())
                             .themes.map(t => t.name)""")
    assert sorted(names) == sorted(api), f"{len(names)} documented vs {len(api)} detected"


PUZZLE_URL = "/#panel=puzzles"

# The `server` fixture's `tables` only generate the KPvk closure (KQvk, KRvk,
# KBvk, KNvk, KPvk, Kvk -- see conftest.py) for speed, while the real
# puzzles.epd Task 4 shipped spans materials well outside it entirely (up to
# 6-man combinations like KBvkqrn, verified by inspection: zero overlap with
# the closure) -- every one of those 404s against this fixture, whichever ten
# pickSession happened to draw. So the set served here is mined out of THAT
# closure instead, and what these tests exercise is the puzzle screen's own
# grading logic rather than whether a speed-oriented fixture happens to have
# generated the right table.
#
# Eleven entries across ten distinct (dtm, piece-count) rungs, which is what
# makes the draw both non-trivial and deterministic:
#
#   * eleven is MORE than SESSION_SIZE, so pickSession does not return early
#     at `sorted.length <= n`. The previous set was exactly ten identical
#     puzzles, which took that early return every time -- the banding
#     arithmetic below it was never reached from a browser at all.
#   * ten rungs against ten slots means bandRanges cuts exactly one rung per
#     band, so slot i is rung i for every i and the only randomness left is
#     WHICH of the two dtm-13 positions fills the last slot.
#
# So puzzle 1 is always the dtm-4 position: a FOUR-ply line, hence two move
# rows rather than one, and a solve that actually reaches
# `plyIndex >= solutionSan.length`. Every (dtm, FEN) pair below was mined out
# of a freshly generated KPvk closure and its line length re-checked against
# it, 2026-08-13.
_PUZZLE_SET = [
    (4,  "8/8/8/8/8/k7/8/1K2Q3 b - -"),      # KQvk -- line: Ka4 Kc2 Ka3 Qa5#
    (5,  "8/8/8/8/8/8/6Q1/K1k5 w - -"),      # KQvk
    (6,  "8/8/8/8/Q7/8/8/K1k5 b - -"),       # KQvk
    (7,  "8/8/8/8/8/8/2Q5/K6k w - -"),       # KQvk
    (8,  "8/8/8/8/8/6k1/5Q2/K7 b - -"),      # KQvk
    (9,  "8/8/7k/5Q2/8/8/1K6/8 w - -"),      # KQvk
    (10, "8/8/7k/6Q1/8/8/1K6/8 b - -"),      # KQvk
    (11, "8/7k/8/6Q1/8/8/8/K7 w - -"),       # KQvk
    (12, "8/8/7k/6Q1/8/8/8/K7 b - -"),       # KQvk
    (13, "6k1/8/8/8/8/8/4P3/2K5 w - -"),     # KPvk -- the doubled rung, so the
    (13, "8/8/7k/8/8/K7/P7/8 w - -"),        # only random slot is the last one
]

# EPD carries no clocks; parseEpd appends the two the rest of the app expects.
FIRST_PUZZLE_FEN = _PUZZLE_SET[0][1] + " 0 1"


def _mock_puzzle_set(page, count=len(_PUZZLE_SET)):
    body = "".join(f'{fen} ; hm {dtm} ; id "p{i}"\n'
                   for i, (dtm, fen) in enumerate(_PUZZLE_SET[:count]))
    page.route("**/puzzles.epd", lambda route: route.fulfill(
        status=200, content_type="text/plain", body=body))


# /v1/line answers in SAN only, so a ply's uci is recovered the same way the
# screen recovers it: match that SAN against /v1/moves for the position
# reached so far. Run in the page so it uses the page's own origin.
_RESOLVE_LINE = """async (fen) => {
  const get = async (path, f) =>
    (await (await fetch(path + '?fen=' + encodeURIComponent(f))).json());
  const line = (await get('/v1/line', fen)).lines[0];
  const out = [];
  let cur = fen;
  for (const san of line) {
    const m = (await get('/v1/moves', cur)).moves.find((x) => x.san === san);
    out.push({ uci: m.uci, san });
    cur = m.fen;
  }
  return out;
}"""

# A LEGAL move that is not the expected one. That is the only wrong move the
# UI can produce: enableBoardInput rejects an illegal drag at
# `candidates.length === 0`, well before judge() is reached, so driving an
# illegal uci through the test hook graded a state the screen cannot reach.
_LEGAL_BUT_UNEXPECTED = """async (fen) => {
  const get = async (path, f) =>
    (await (await fetch(path + '?fen=' + encodeURIComponent(f))).json());
  const expected = (await get('/v1/line', fen)).lines[0][0];
  return (await get('/v1/moves', fen)).moves.find((m) => m.san !== expected).uci;
}"""


def _revealed(page):
    return page.eval_on_selector("#puzzle-line", "e => e.classList.contains('revealed')")


def test_a_puzzle_screen_opens_with_a_prompt_and_a_board(page, server):
    _mock_puzzle_set(page)
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    prompt = page.inner_text("#puzzle-prompt")
    assert "h#" in prompt
    assert "1 of 10" in page.inner_text("#puzzle-progress")


def test_playing_the_whole_line_marks_every_ply_and_reports_it_solved(page, server):
    # The screen's entire point, and it had no coverage: the previous version
    # of this test clicked "Show solution" and asserted a span was non-empty,
    # which reveal() alone satisfies. judge()'s success branch and
    # afterJudge()'s success half could both be deleted whole and it passed;
    # finishPuzzle() and #puzzle-solved were never reached at all. So: play
    # every ply of a real line through the same grading path a drag uses.
    # A single-puzzle session so that finishing it also ends the session --
    # closing state (solved++) gets asserted below via the summary, which
    # `finishPuzzle()` alone does not touch.
    _mock_puzzle_set(page, count=1)
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    plies = page.evaluate(_RESOLVE_LINE, FIRST_PUZZLE_FEN)

    assert len(plies) == 4, plies
    # four plies pair into two move rows -- a multi-row line, which a set of
    # 2-ply puzzles never produced
    assert page.eval_on_selector_all("#puzzle-line .move-row", "e => e.length") == 2
    assert page.eval_on_selector_all("#puzzle-line .ply", "e => e.length") == 4
    assert page.is_hidden("#puzzle-solved")

    for i, ply in enumerate(plies):
        page.evaluate("u => window.__puzzlePlay(u)", ply["uci"])
        page.wait_for_selector(f"#puzzle-line .ply[data-ply='{i}'].correct")
        assert page.eval_on_selector(
            f"#puzzle-line .ply[data-ply='{i}']", "e => e.textContent.trim()") == ply["san"]

    assert page.eval_on_selector_all("#puzzle-line .ply.correct", "e => e.length") == 4
    assert page.eval_on_selector_all("#puzzle-line .ply.wrong", "e => e.length") == 0
    # graded, not revealed -- reveal() would also have filled every cell
    assert not _revealed(page), "the line was revealed, not solved"
    assert page.is_hidden("#puzzle-correction")

    page.wait_for_selector("#puzzle-solved:not([hidden])")
    assert "Solved" in page.inner_text("#puzzle-solved")
    assert plies[-1]["san"].endswith("#"), plies[-1]

    # finishPuzzle()'s solved++ has to actually land somewhere observable:
    # ending the (single-puzzle) session must report one solved, not zero.
    page.click("#btn-puzzle-next")
    page.wait_for_function(
        "() => document.getElementById('puzzle-progress').textContent.includes('complete')")
    assert "1 of 1 solved" in page.inner_text("#puzzle-progress")
    assert "Nice work" in page.inner_text("#puzzle-prompt")


def test_a_legal_but_unexpected_move_is_marked_wrong_and_does_not_advance(page, server):
    _mock_puzzle_set(page)
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    wrong = page.evaluate(_LEGAL_BUT_UNEXPECTED, FIRST_PUZZLE_FEN)
    assert len(wrong) == 4, wrong

    page.evaluate("u => window.__puzzlePlay(u)", wrong)
    page.wait_for_selector("#puzzle-line .ply.wrong")
    assert page.eval_on_selector_all("#puzzle-line .ply.wrong", "e => e.length") == 1
    assert page.eval_on_selector("#puzzle-line .ply.wrong", "e => e.dataset.ply") == "0"
    assert page.is_visible("#puzzle-correction")

    plies = page.evaluate(_RESOLVE_LINE, FIRST_PUZZLE_FEN)
    assert page.inner_text("#puzzle-correction") == f"Correct move: {plies[0]['san']}"
    # the ply the player still owes is ungraded, and the position is untouched:
    # playing it now is accepted as ply 0
    assert page.eval_on_selector_all("#puzzle-line .ply.correct", "e => e.length") == 0
    page.evaluate("u => window.__puzzlePlay(u)", plies[0]["uci"])
    page.wait_for_selector("#puzzle-line .ply[data-ply='0'].correct")


def test_a_legal_but_unexpected_drag_snaps_the_piece_back(page, server):
    # validateMoveInput returns judge()'s answer, so a wrong move must be
    # REJECTED as a drag -- the piece returns to its square and the board
    # still shows the position the player has to solve.
    _mock_puzzle_set(page)
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    wrong = page.evaluate(_LEGAL_BUT_UNEXPECTED, FIRST_PUZZLE_FEN)
    frm, to = wrong[:2], wrong[2:4]

    a = page.locator(f"#puzzle-board rect[data-square={frm}]").bounding_box()
    b = page.locator(f"#puzzle-board rect[data-square={to}]").bounding_box()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=10)
    page.mouse.up()

    page.wait_for_selector("#puzzle-line .ply.wrong")
    page.wait_for_timeout(400)      # let cm-chessboard finish animating the piece back
    occupied = "#puzzle-board g[data-piece][data-square='%s']"
    assert page.eval_on_selector_all(occupied % frm, "e => e.length") == 1, \
        "the rejected drag left the origin square empty"
    assert page.eval_on_selector_all(occupied % to, "e => e.length") == 0, \
        "the rejected drag was played anyway"


def test_the_error_budget_decides_when_the_line_is_revealed(page, server):
    # A budget DIFFERENT from puzzle.js's own default of 1: setting it to 1
    # was a no-op, so both a no-op __puzzleSetBudget and `errors > 0` passed.
    # Both directions are pinned here -- errors inside the budget must NOT
    # reveal, the first one past it must.
    _mock_puzzle_set(page)
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    wrong = page.evaluate(_LEGAL_BUT_UNEXPECTED, FIRST_PUZZLE_FEN)
    page.evaluate("window.__puzzleSetBudget(2)")

    page.evaluate("u => window.__puzzlePlay(u)", wrong)
    page.wait_for_selector("#puzzle-line .ply.wrong")
    assert not _revealed(page), "one error, inside a budget of 2, revealed the line"

    page.evaluate("u => window.__puzzlePlay(u)", wrong)
    assert not _revealed(page), "two errors, equal to the budget, revealed the line"

    page.evaluate("u => window.__puzzlePlay(u)", wrong)
    page.wait_for_selector("#puzzle-line.revealed")
    filled = page.eval_on_selector_all(
        "#puzzle-line .ply", "els => els.map(e => e.textContent.trim())")
    assert all(filled), filled


def test_a_superseded_puzzles_load_error_does_not_overwrite_the_current_one(page, server):
    # movesWithRetry's catch was the last exit with no staleness check.
    # Puzzle 1 sits on a table that is still downloading; the user clicks
    # "Next puzzle" and puzzle 2 loads fine; then puzzle 1's abandoned
    # request finally rejects -- /v1/moves answers a failed download with a
    # real 500 -- and the error overwrote puzzle 2's prompt, naming a
    # material that is not on the board. Puzzle 1's request is held open in
    # the page and released by hand, so this is deterministic.
    _mock_puzzle_set(page)
    page.add_init_script("""
      window.__failStaleMoves = null;
      const orig = window.fetch;
      let held = false;
      window.fetch = function (input, init) {
        if (!held && String(input).includes("/v1/moves")) {
          held = true;
          return new Promise((resolve) => {
            window.__failStaleMoves = () => resolve(new Response(
              JSON.stringify({error: {code: "internal",
                                      message: "download of 'KQvk' failed"}}),
              {status: 500, headers: {"content-type": "application/json"}}));
          });
        }
        return orig.call(window, input, init);
      };
    """)
    page.goto(server + PUZZLE_URL)
    page.wait_for_function("window.__failStaleMoves !== null")

    page.click("#btn-puzzle-next")
    page.wait_for_selector("#puzzle-line .ply")
    assert "2 of 10" in page.inner_text("#puzzle-progress")
    prompt = page.inner_text("#puzzle-prompt")

    page.evaluate("window.__failStaleMoves()")     # puzzle 1's request fails now
    page.wait_for_timeout(400)
    assert page.inner_text("#puzzle-prompt") == prompt, \
        "a superseded puzzle's load error overwrote the puzzle on screen"


def _endpoint_hits(urls, path):
    """Requests to exactly `path`, ignoring anything nested under it.

    "/v1/materials" is a prefix of "/v1/materials/KQvk/stats", so a substring
    count would report the catalog as fetched every time a material's stats
    are opened.
    """
    return [u for u in urls if urlparse(u).path == path]


def test_a_hidden_screen_costs_nothing_at_page_load(page, server):
    # First paint used to run every screen's init unconditionally: the puzzle
    # screen fetched puzzles.epd, the material catalog AND a whole puzzle's
    # /v1/moves -- which, on an install with a remote table chain, answers 202
    # and STARTS A DOWNLOAD, polled for up to a minute, for a panel nobody has
    # opened. /v1/materials and /v1/themes were each fetched twice for the
    # same reason. Every screen's first paint is now deferred to its panel's
    # first activation.
    #
    # Kept on the shipped default (search off), not server_mining: this is
    # exactly the config this task changed boot order for -- the boot now
    # awaits /v1/health before deciding anything, and initMine() does not
    # run at all -- so /v1/themes must be 0 here, not 1. (initMine()'s eager
    # theme-picker populate was the one legitimate /v1/themes hit; with
    # mining off, nothing at boot touches it.)
    _mock_puzzle_set(page)
    urls = []
    page.on("request", lambda r: urls.append(r.url))
    page.goto(f"{server}/#panel=materials")
    page.wait_for_function("window.__materialsReady === true")
    page.wait_for_timeout(300)

    assert _endpoint_hits(urls, "/v1/moves") == [], "a hidden screen probed a position"
    assert _endpoint_hits(urls, "/puzzles.epd") == [], "a hidden screen fetched the puzzle set"
    assert len(_endpoint_hits(urls, "/v1/materials")) == 1, "the catalog was fetched twice"
    assert len(_endpoint_hits(urls, "/v1/themes")) == 0, \
        "search is off -- nothing at boot should touch the theme registry"

    # ...and opening the panel does pay for it, so the assertions above are
    # about laziness, not about the screen having quietly stopped working.
    page.click("nav button[data-panel=puzzles]")
    page.wait_for_selector("#puzzle-line .ply")
    assert _endpoint_hits(urls, "/puzzles.epd")
    assert _endpoint_hits(urls, "/v1/moves")


def test_a_deep_link_to_another_screen_shows_no_explorer_error(page, empty_server):
    # An install with no tables at all -- the first-run state of every public
    # release. The explorer probed its landing position at page load whatever
    # panel was active, and #error-banner lives OUTSIDE <main>, so a
    # "#panel=themes" link painted a red "no table for material 'KQvk'" over a
    # screen the user never opened.
    page.goto(f"{empty_server}/#panel=themes")
    page.wait_for_selector("#themes-doc .theme-entry")
    assert page.is_hidden("#error-banner"), page.inner_text("#error-banner")

    # The banner is still right where it belongs: on the explorer, which on
    # this corpus genuinely cannot answer. Without this the assertion above
    # would also pass if the banner had simply stopped working.
    page.click("nav button[data-panel=explorer]")
    page.wait_for_selector("#error-banner:not([hidden])")


def test_a_footer_link_keeps_the_position_it_was_clicked_from(page, server):
    # The successor to the placeholder-cannot-navigate test. Those links now
    # DO navigate -- that is their job -- so the property that survived is
    # the one the old `href="#"` bug actually violated: the position you were
    # looking at must still be there when you come back.
    #
    # `href="#panel=privacy"` alone would drop the fen parameter, because it
    # replaces the whole hash. panels.js's delegated a[data-panel] handler
    # re-encodes the current fen alongside the new panel; this is what asserts
    # that handler exists and is wired to the footer, not just to About.
    page.goto(f"{server}/#fen={quote(SATURATED)}")
    page.wait_for_selector("#move-list li")
    page.click("footer a[data-panel='privacy']")
    page.wait_for_selector("#panel-privacy:not([hidden])")
    assert not page.is_visible("#panel-explorer")
    # Decoded, not string-matched: the handler re-encodes through
    # URLSearchParams, which is free to spell a space `+` and a slash `%2F`.
    # What matters is that the fen round-trips, not how it is spelt.
    hash_state = parse_qs(urlparse(page.url).fragment)
    assert hash_state.get("fen") == [SATURATED], page.url
    assert hash_state.get("panel") == ["privacy"], page.url

    # ...and back, onto the same position rather than the landing default.
    page.click("nav button[data-panel=explorer]")
    page.wait_for_selector("#panel-explorer:not([hidden])")
    assert page.input_value("#fen-input") == SATURATED


def test_a_session_nobody_solved_is_not_congratulated(page, server):
    # "Nice work -- 10 of 10" was printed whatever happened, including to
    # someone who got every ply wrong. Two puzzles, neither solved.
    _mock_puzzle_set(page, count=2)
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    page.click("#btn-puzzle-next")
    page.wait_for_selector("#puzzle-line .ply")
    page.click("#btn-puzzle-next")
    page.wait_for_function(
        "() => document.getElementById('puzzle-progress').textContent.includes('complete')")
    prompt = page.inner_text("#puzzle-prompt")
    progress = page.inner_text("#puzzle-progress")
    assert "Nice work" not in prompt, prompt
    assert "None solved" in prompt, prompt
    assert "0 of 2 solved" in progress, progress


def test_an_installation_with_no_matching_tables_says_so_and_keeps_saying_it(page, empty_server):
    # No tables at all, and the REAL puzzles.epd (no route mock): every puzzle
    # in the set is unplayable, so the screen must name what to generate --
    # and pressing "Next puzzle" must not replace that with a summary of a
    # session that never ran ("Nice work -- 0 of 0").
    page.goto(empty_server + PUZZLE_URL)
    page.wait_for_function(
        "() => document.getElementById('puzzle-prompt').textContent.includes('helpmate gen')")
    page.click("#btn-puzzle-next")
    page.wait_for_timeout(400)
    prompt = page.inner_text("#puzzle-prompt")
    assert "Nice work" not in prompt, prompt
    assert "0 of 0" not in page.inner_text("#puzzle-progress")
    assert "helpmate gen" in prompt, prompt

    # And the table it names is one of the set's CHEAP closures, not the
    # alphabetically first name in a sorted list -- which is KBBvkbb, a 6-man
    # table, recommended to someone who has generated nothing at all.
    named = re.search(r"helpmate gen (\S+)", prompt).group(1)
    men = len(named) - 1          # the "v" separates the sides, it is not a piece
    assert men == 4, f"recommended {named}, a {men}-man table"


def test_the_puzzle_feedback_is_announced_to_assistive_tech(page, server):
    # Correct/wrong/solved is the screen's only feedback, and none of it was
    # announced: nothing in the static tree carried aria-live or role.
    _mock_puzzle_set(page)
    page.goto(server + PUZZLE_URL)
    page.wait_for_selector("#puzzle-line .ply")
    for sel in ("#puzzle-correction", "#puzzle-solved"):
        role = page.get_attribute(sel, "role")
        assert role == "status", f"{sel} has role {role!r}"


# ---------------------------------------------------------------- chrome ----
#
# "The board must be fixed, the right side scrolls." The board itself already
# pinned (see _sticky_is_wired above); what scrolled away was everything
# around it -- the brand, the nav and the server chip -- which left the board
# jammed against the top edge of the window with its piece tray clipped.


def test_the_header_stays_put_while_the_page_scrolls(page, server):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server}/#fen={quote(SATURATED)}")
    page.wait_for_selector("#move-list li")
    page.mouse.wheel(0, 1200)
    page.wait_for_function("() => window.scrollY > 0")
    top = page.eval_on_selector("body > header", "e => e.getBoundingClientRect().top")
    assert top == 0, f"header drifted to {top} after scrolling"


def test_the_pinned_board_comes_to_rest_below_the_header_not_behind_it(page, server):
    """Two failures in one assertion, and they fail in opposite directions.

    Too small an offset and the board slides under a header that now
    permanently occupies the top of the viewport -- which is worse than the
    original bug, because the header is opaque. Too large and there is a strip
    of scrolling move list visible above a board that claims to be pinned.
    """
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server}/#fen={quote(SATURATED)}")
    page.wait_for_selector("#move-list li")
    page.mouse.wheel(0, 1400)
    page.wait_for_function("() => window.scrollY > 0")
    m = page.evaluate("""() => ({
      headerBottom: document.querySelector('body > header').getBoundingClientRect().bottom,
      pinTop: document.querySelector('.board-pin').getBoundingClientRect().top,
    })""")
    gap = m["pinTop"] - m["headerBottom"]
    assert gap >= 0, f"board overlaps the header by {-gap:.1f}px"
    assert gap < 40, f"board rests {gap:.1f}px below the header"


def test_the_pin_offset_is_measured_from_the_real_header(page, server):
    """--header-h is a JS-published measurement with a CSS fallback, and the
    fallback is only right for the unwrapped header. Between roughly 860 and
    1100px the header wraps to two lines; if the fallback were being used
    instead of the measurement, the board would pin behind it at that width.
    Assert the published value tracks the element at BOTH widths, so a
    regression that drops js/chrome.js is caught rather than passing at the
    one width where the constant happens to be correct.
    """
    page.goto(server)
    page.wait_for_function("() => window.__chipReady === true")
    for width in (1440, 900):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(150)
        m = page.evaluate("""() => ({
          real: document.querySelector('body > header').getBoundingClientRect().height,
          token: parseFloat(getComputedStyle(document.documentElement)
                   .getPropertyValue('--header-h')),
        })""")
        assert abs(m["real"] - m["token"]) < 1, f"at {width}px: {m}"


def test_a_doc_screens_own_heading_is_not_sticky(page, server):
    """`header { position: sticky }` is an element selector, and About,
    Technique and Privacy each open with their own <header class="doc-head">.
    Unscoped, that rule pinned three more bars to the top of the window."""
    page.goto(f"{server}/#panel=about")
    page.wait_for_selector("#panel-about:not([hidden])")
    pos = page.eval_on_selector(
        "#panel-about .doc-head", "e => getComputedStyle(e).position")
    assert pos == "static", f"doc heading is {pos}"


def test_the_board_is_lifted_off_the_rail(page, server):
    page.goto(server)
    page.wait_for_selector("#board svg")
    shadow = page.eval_on_selector("#board", "e => getComputedStyle(e).boxShadow")
    assert shadow != "none", "board has no shadow"
    # Three layers: a hairline edge, a contact shadow and a cast. A single
    # layer is a flat drop shadow, which is what this replaced.
    assert shadow.count("rgba") >= 3, shadow


# ------------------------------------------------------- about / technique --


def test_the_explorer_carries_a_short_about_with_working_links(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.is_visible(".about-card")
    page.click(".about-links a[data-panel='technique']")
    page.wait_for_selector("#panel-technique:not([hidden])")
    assert not page.is_visible("#panel-explorer")


@pytest.mark.parametrize("panel", ["about", "technique", "privacy"])
def test_each_prose_screen_opens_on_its_own(page, server, panel):
    """Reachable by deep link, and exclusive -- panels.js derives its list
    from the DOM, so a new <section id="panel-*"> is wired the moment it
    exists. That is the mechanism these three rely on, and Technique and
    Privacy have no nav button of their own to fall back on."""
    page.goto(f"{server}/#panel={panel}")
    page.wait_for_selector(f"#panel-{panel}:not([hidden])")
    shown = page.eval_on_selector_all(
        "main > section[id^='panel-']:not([hidden])", "els => els.map(e => e.id)")
    assert shown == [f"panel-{panel}"]
    assert page.inner_text(f"#panel-{panel} .doc-head h2").strip()


def test_the_prose_screens_hold_a_readable_measure(page, server):
    """1200px of panel is roughly 170 characters of this body size. Prose that
    wide is not readable, and these three screens are the only long-form text
    on the site."""
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server}/#panel=technique")
    page.wait_for_selector("#panel-technique:not([hidden])")
    width = page.eval_on_selector(
        "#panel-technique .doc-section p", "e => e.getBoundingClientRect().width")
    assert 380 <= width <= 720, f"prose column is {width:.0f}px"


def test_privacy_states_the_no_storage_claim_the_code_actually_backs(page, server):
    """The Privacy screen claims this site sets no cookies and uses neither
    local nor session storage. That is a claim about the shipped JavaScript,
    so assert it against a real page load rather than against the prose."""
    page.goto(server)
    page.wait_for_selector("#move-list li")
    page.click("nav button[data-panel=puzzles]")
    page.wait_for_selector("#panel-puzzles:not([hidden])")
    page.click("nav button[data-panel=materials]")
    page.wait_for_selector("#material-list li")
    state = page.evaluate("""() => ({
      cookie: document.cookie,
      local: Object.keys(localStorage).length,
      session: Object.keys(sessionStorage).length,
    })""")
    assert state == {"cookie": "", "local": 0, "session": 0}, state
