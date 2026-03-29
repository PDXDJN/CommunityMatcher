"""
Adapter smoke tests — verify structure and behaviour without live sites.
No real browser launched here; adapters are imported and inspected.
"""
import pytest
from community_collector.adapters.base import BaseSourceAdapter
from community_collector.adapters.meetup_adapter import MeetupAdapter
from community_collector.adapters.eventbrite_adapter import EventbriteAdapter
from community_collector.adapters.luma_adapter import LumaAdapter
from community_collector.config import CollectorConfig


def test_meetup_adapter_is_base_subclass():
    assert issubclass(MeetupAdapter, BaseSourceAdapter)


def test_eventbrite_adapter_is_base_subclass():
    assert issubclass(EventbriteAdapter, BaseSourceAdapter)


def test_luma_adapter_is_base_subclass():
    assert issubclass(LumaAdapter, BaseSourceAdapter)


def test_all_adapters_have_source_name():
    for cls in (MeetupAdapter, EventbriteAdapter, LumaAdapter):
        instance = cls()
        assert isinstance(instance.source_name, str)
        assert len(instance.source_name) > 0


def test_all_adapters_have_collect_method():
    for cls in (MeetupAdapter, EventbriteAdapter, LumaAdapter):
        assert callable(getattr(cls, "collect", None))


def test_collector_config_defaults():
    config = CollectorConfig()
    assert config.location == "Berlin"
    assert config.headless is True
    assert config.max_results_per_source == 20
    assert "meetup" in config.sources_to_run


def test_collector_config_custom():
    config = CollectorConfig(
        location="London",
        search_terms=["python"],
        sources_to_run=["meetup"],
        max_results_per_source=5,
    )
    assert config.location == "London"
    assert config.search_terms == ["python"]


@pytest.mark.skip(reason="Requires live browser — run manually with: pytest -k live")
async def test_meetup_adapter_live():
    """Live smoke test — run manually to validate against real site."""
    from playwright.async_api import async_playwright
    config = CollectorConfig(
        location="Berlin",
        search_terms=["python"],
        max_results_per_source=3,
        headless=True,
    )
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        adapter = MeetupAdapter()
        results = await adapter.collect(browser, config, "python")
        await browser.close()
    assert isinstance(results, list)


def test_persistence_init_creates_tables(tmp_path):
    """DB init should create all tables without errors."""
    from community_collector.persistence import init_db
    import sqlite3
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    for expected in ("community", "social", "keyword", "kw_affinity", "scrape_record", "scrape_run"):
        assert expected in tables, f"Missing table: {expected}"


def test_save_records_round_trip(tmp_path):
    """Save a record to SQLite and verify it appears in community table."""
    import sqlite3
    from community_collector.models import CommunityEventRecord
    from community_collector.persistence import save_records
    db_path = str(tmp_path / "test.db")
    rec = CommunityEventRecord(
        source="meetup",
        source_url="https://meetup.com/test-group/events/1",
        title="Test Python Meetup",
        description="A test meetup about Python",
        tags=["python", "coding"],
        topic_signals=["python"],
        cost_factor=0.0,
        city="Berlin",
    )
    count = save_records([rec], db_path)
    assert count == 1
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT name FROM community WHERE name = ?", ("Test Python Meetup",)).fetchone()
    conn.close()
    assert row is not None
