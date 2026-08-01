from urllib.parse import quote

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
