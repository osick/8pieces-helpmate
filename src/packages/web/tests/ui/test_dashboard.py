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
    page.click("#fen-form button[type=submit]")
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
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.is_visible("#panel-explorer")
    assert not page.is_visible("#panel-materials")
    assert not page.is_visible("#panel-mine")

    page.click("nav button[data-panel=materials]")
    assert not page.is_visible("#panel-explorer")
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


def test_the_palette_places_a_piece_and_evaluates_on_exit(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    before = page.input_value("#fen-input")

    # Move the queen from g1 to d4 by erasing and placing. Both ends stay
    # inside KQvk, the only closure the fixture generated.
    # rect[]: piece groups carry data-square too, and their layer has
    # pointer-events: none, so only the square rects are clickable.
    page.click("#btn-erase")
    assert page.get_attribute("#btn-erase", "aria-pressed") == "true"
    # entering edit mode retires the old position's value rather than
    # leaving a stale dtm on screen
    assert "dtm" not in page.inner_text("#position-summary")
    assert page.eval_on_selector_all("#move-list li", "els => els.length") == 0

    page.click("#board rect[data-square=g1]")
    page.wait_for_function(
        "before => document.getElementById('fen-input').value !== before", arg=before)
    assert "Q" not in page.input_value("#fen-input").split()[0]

    page.click("#palette-pieces button[data-piece=wq]")
    assert page.get_attribute("#btn-erase", "aria-pressed") == "false"
    assert page.get_attribute("#palette-pieces button[data-piece=wq]", "aria-pressed") == "true"
    page.click("#board rect[data-square=d4]")
    page.wait_for_function(
        "document.getElementById('fen-input').value.startsWith('8/7k/5K2/8/3Q4/')")

    # Editing does not probe on every click -- the value appears when the
    # user leaves edit mode by clicking the armed piece again.
    page.click("#palette-pieces button[data-piece=wq]")
    assert page.get_attribute("#palette-pieces button[data-piece=wq]", "aria-pressed") == "false"
    page.wait_for_function(
        "document.getElementById('position-summary').textContent.includes('dtm')")
    assert page.eval_on_selector_all("#move-list li", "els => els.length") > 0
    assert page.is_hidden("#error-banner")


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


def test_mine_search_and_client_side_validation(page, server):
    page.goto(f"{server}/#panel=mine")
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


def test_theme_picker_is_populated_from_the_server(page, server):
    page.goto(f"{server}/#panel=mine")
    page.wait_for_selector("#mine-themes option")
    values = page.eval_on_selector_all(
        "#mine-themes option", "els => els.map(e => e.value)")
    assert "model" in values and "closed-walk" in values


def test_theme_picker_marks_themes_that_answer_on_saturated_positions(page, server):
    # Task 10: any theme whose `needs` isn't "solutions" still answers on
    # positions whose stored solution count has saturated (capped at 255) --
    # the picker must mark those, driven by the server's own `needs` field,
    # not by a hard-coded theme name.
    import json
    import urllib.request
    with urllib.request.urlopen(f"{server}/v1/themes") as r:
        registry = json.load(r)["themes"]
    non_solutions = {t["name"] for t in registry if t["needs"] != "solutions"}
    assert non_solutions, "fixture build must register at least one non-Solutions theme"

    page.goto(f"{server}/#panel=mine")
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


def test_selecting_two_themes_sends_both_not_just_the_last(page, server):
    # Regression: Object.fromEntries(new FormData(form).entries()) keeps only
    # the LAST value of a repeated field. A naive read of the multi-select
    # would silently narrow a two-theme search down to one -- the exact class
    # of bug this project has hit before, so assert on the actual request the
    # browser sends rather than trusting the picker looks right on screen.
    page.goto(f"{server}/#panel=mine")
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
    assert badges == ["h#4.5 · 246 ways", "h#4.5 · 255+ ways"]
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
        "#move-list li .badge", "e => e.textContent") == "h#0 · only reply"

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


def test_the_board_stays_put_while_the_answer_scrolls(page, server):
    # Syzygy's structural win, without its 310px cap: a long move list must
    # never drag the board off screen. No sticky headers, no scroll sync --
    # position: sticky on .board-pin, and only above the breakpoint.
    # Fix round 1: sticky moved off .board-col (the rail, which fix round 1
    # stretches to the readout's full height so its background covers the
    # whole column -- see the C2 comment in app.css) onto .board-pin, the
    # inner wrapper around #board and .palette that is still only as tall as
    # its own content. So this now asserts on .board-pin, not .board-col.
    page.set_viewport_size({"width": 1280, "height": 700})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")   # 28 moves: taller than the viewport
    page.wait_for_selector("#move-list li")
    page.mouse.wheel(0, 600)
    page.wait_for_function("() => window.scrollY > 100")
    top_after = page.eval_on_selector(".board-pin", "e => e.getBoundingClientRect().top")
    # Without sticky this is around -500 (scrolled off the top). With it, the
    # column parks at --s3 from the viewport top and stays there.
    assert top_after >= 0, f"the board column scrolled out of view (top={top_after})"
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
    for sel in ("#palette", "#fen-form", "#move-list", "#btn-export-pgn"):
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


def test_theme_toggle_cycles_all_three_states_and_persists(page, server):
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.get_attribute("#theme-toggle", "data-mode") == "system"
    assert page.evaluate(
        "document.documentElement.hasAttribute('data-theme')") is False
    assert page.inner_text("#theme-toggle") == "Theme: system"

    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") == "light"
    page.click("#theme-toggle")
    assert page.get_attribute("html", "data-theme") == "dark"
    assert page.inner_text("#theme-toggle") == "Theme: dark"

    # The choice survives a reload -- and is applied before first paint, so
    # a dark-mode user never gets a white flash.
    page.reload()
    page.wait_for_selector("#move-list li")
    assert page.get_attribute("html", "data-theme") == "dark"

    page.click("#theme-toggle")   # back round to system
    assert page.evaluate(
        "document.documentElement.hasAttribute('data-theme')") is False


def test_an_explicit_light_choice_beats_a_dark_operating_system(browser, server):
    # The three-state point: prefers-color-scheme is the DEFAULT, not the
    # authority. If the media query were unguarded, a dark OS would win and
    # the light setting would do nothing.
    ctx = browser.new_context(color_scheme="dark")
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_selector("#move-list li")
    dark_bg = pg.eval_on_selector("body", "e => getComputedStyle(e).backgroundColor")
    pg.click("#theme-toggle")   # -> light
    assert pg.get_attribute("html", "data-theme") == "light"
    light_bg = pg.eval_on_selector("body", "e => getComputedStyle(e).backgroundColor")
    assert light_bg != dark_bg, "explicit light did not override the dark OS"
    ctx.close()


def test_the_theme_toggle_is_not_treated_as_a_panel_button(page, server):
    # panels.js binds EVERY `nav button` as a panel switch and reads
    # btn.dataset.panel. A stray button inside <nav> would call
    # showPanel(undefined) on click and hide all three panels at once -- a
    # failure that looks like a blank page and has no other test guarding it.
    page.goto(server)
    page.wait_for_selector("#move-list li")
    assert page.eval_on_selector("#theme-toggle", "e => e.closest('nav') === null")
    page.click("#theme-toggle")
    assert page.is_visible("#panel-explorer")


def test_search_results_are_numbered_and_open_in_the_explorer(page, server):
    page.goto(f"{server}/#panel=mine")
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
    page.set_viewport_size({"width": 1280, "height": 700})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")
    page.wait_for_selector("#move-list li")
    before = page.eval_on_selector("#board", "e => e.getBoundingClientRect().top")
    page.evaluate("window.scrollBy(0, 400)")
    page.wait_for_timeout(100)
    after = page.eval_on_selector("#board", "e => e.getBoundingClientRect().top")
    assert after > before - 400 + 50, "the board scrolled away instead of sticking"
    assert after >= -1, "the board is above the viewport"


def test_the_explorer_shows_the_table_this_position_came_from(page, server):
    page.goto(server)
    page.wait_for_selector("#table-stats .stats-head")
    assert "KQvk" in page.inner_text("#table-stats .stats-head")
    # its own ids, so the Materials panel's charts stay uniquely selectable
    assert page.eval_on_selector_all("#tbl-dtm-hist", "e => e.length") == 1
    assert page.eval_on_selector_all("#dtm-hist", "e => e.length") == 0
    # and no sample list -- the explorer already is a position
    assert page.eval_on_selector_all("#tbl-material-samples", "e => e.length") == 0


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
    page.wait_for_selector("#table-stats .stats-head")
    assert "KQvk" in page.inner_text("#table-stats .stats-head")

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
    page.wait_for_selector("#table-stats .stats-head")
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


def test_a_timed_out_search_says_so_instead_of_reporting_no_results(page, server):
    # The server answers a timeout with {fens: [], truncated: true,
    # note: "timeout"}. Rendering that as "0 position(s) (truncated -- raise
    # max results for more)" is advice that cannot help, about a result that
    # was never computed.
    page.goto(f"{server}/#panel=mine")
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


def test_the_search_button_becomes_stop_while_in_flight(page, server):
    page.goto(f"{server}/#panel=mine")
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


def test_the_countdown_uses_the_servers_budget(page, server):
    page.goto(f"{server}/#panel=mine")
    page.route("**/v1/mine**", lambda route: None)
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "2")
    page.click("#mine-form button[type=submit]")
    page.wait_for_function(
        "document.getElementById('mine-status').textContent.includes('of 30s')")


def test_the_search_rail_matches_the_readout_height(page, server):
    # Same defect class as the explorer's .board-pin and materials'
    # .materials-pin fixes (see the Fix round 1 comment at .board-pin in
    # app.css): #mine-form/.rail must stretch to the grid row's full height
    # while .mine-pin carries the sticky behaviour at its own, shorter
    # height -- or the strip below the form paints --readout instead of
    # --rail once the results list outgrows the form fields. dtm=1 on the
    # KQvk fixture returns 50 rows (measured 2026-08-12), reliably taller
    # than the six-field form.
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{server}/#panel=mine")
    page.fill("#mine-form input[name=material]", "KQvk")
    page.fill("#mine-form input[name=dtm]", "1")
    page.click("#mine-form button[type=submit]")
    page.wait_for_selector("#mine-results li")
    rail = page.eval_on_selector("#mine-form", "e => e.getBoundingClientRect()")
    readout = page.eval_on_selector("#panel-mine .readout", "e => e.getBoundingClientRect()")
    assert abs(rail["bottom"] - readout["bottom"]) <= 2, (
        f"rail bottom {rail['bottom']:.1f} != readout bottom {readout['bottom']:.1f}")
