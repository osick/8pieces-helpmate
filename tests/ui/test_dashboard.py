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
