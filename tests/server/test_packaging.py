def test_import_and_version():
    import helpmate_server
    assert helpmate_server.__version__ == "0.7.0"

def test_console_script_targets_exist():
    from helpmate_server.main import main as server_main
    from helpmate_server.tables_cli import main as tables_main
    assert callable(server_main) and callable(tables_main)
