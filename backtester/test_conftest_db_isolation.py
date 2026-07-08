def test_database_url_points_to_a_dedicated_test_db_not_the_dev_db():
    """
    Regression test: running a manually-started `python main.py` dev server
    concurrently with pytest caused cross-process sweep interference, since
    both processes shared the same backtester.db file (see orchestrator
    flakiness diagnosed this session). conftest.py must force DATABASE_URL to
    a dedicated file before any test module imports config/database, so
    pytest never touches backtester.db regardless of what else is running.
    """
    import config
    assert not config.DATABASE_URL.endswith("backtester.db")
    assert "pytest" in config.DATABASE_URL
