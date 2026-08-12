from urllib.parse import quote, urlparse, parse_qs

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
    # position: sticky on the board column, and only above the breakpoint.
    page.set_viewport_size({"width": 1280, "height": 700})
    page.goto(f"{server}/#fen={quote(THREE_GROUPS)}")   # 28 moves: taller than the viewport
    page.wait_for_selector("#move-list li")
    page.mouse.wheel(0, 600)
    page.wait_for_function("() => window.scrollY > 100")
    top_after = page.eval_on_selector(".board-col", "e => e.getBoundingClientRect().top")
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
