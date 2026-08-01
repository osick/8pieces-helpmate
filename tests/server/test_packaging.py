def test_import():
    import helpmate_server
    # Version consistency is asserted in tests/repo/test_version_consistency.py
    assert hasattr(helpmate_server, "__version__")

def test_console_script_targets_exist():
    from helpmate_server.main import main as server_main
    from helpmate_server.tables_cli import main as tables_main
    assert callable(server_main) and callable(tables_main)
