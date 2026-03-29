from community_collector.normalization import normalize
from community_collector.utils.date_utils import parse_cost_factor, infer_activity
from community_collector.utils.url_utils import normalize_url


def test_normalize_meetup_valid():
    raw = {
        "url": "https://www.meetup.com/berlin-python/events/123/",
        "title": "Berlin Python Night",
        "group_name": "Berlin Python Users",
        "description": "Monthly meetup for Python enthusiasts",
        "datetime": "Thursday, 15 Feb 2026 19:00",
        "venue": "Factory Berlin",
        "city": "Berlin",
        "country": "Germany",
        "search_term": "python",
        "source": "meetup",
    }
    rec = normalize(raw, "meetup")
    assert rec is not None
    assert rec.source == "meetup"
    assert "python" in rec.topic_signals
    assert rec.city == "Berlin"


def test_normalize_eventbrite_valid():
    raw = {
        "url": "https://www.eventbrite.com/e/ai-hackathon-123",
        "title": "AI Hackathon Berlin 2026",
        "organizer": "TechHub Berlin",
        "price": "Free",
        "city": "Berlin",
        "country": "Germany",
        "search_term": "AI",
        "source": "eventbrite",
    }
    rec = normalize(raw, "eventbrite")
    assert rec is not None
    assert rec.cost_factor == 0.0
    assert "free" in rec.tags


def test_normalize_skips_missing_title():
    raw = {"url": "https://meetup.com/x", "title": "", "source": "meetup"}
    rec = normalize(raw, "meetup")
    assert rec is None


def test_normalize_skips_missing_url():
    raw = {"url": "", "title": "Test Event", "source": "meetup"}
    rec = normalize(raw, "meetup")
    assert rec is None


def test_parse_cost_factor_free():
    assert parse_cost_factor("Free") == 0.0
    assert parse_cost_factor("kostenlos") == 0.0
    assert parse_cost_factor("€0") == 0.0


def test_parse_cost_factor_paid():
    assert parse_cost_factor("€10") == 10.0
    assert parse_cost_factor("€5 – €20") == 12.5


def test_parse_cost_factor_unknown():
    assert parse_cost_factor(None) is None
    assert parse_cost_factor("") is None


def test_infer_activity_weekly():
    assert infer_activity("This is a weekly coding meetup") == "weekly"


def test_infer_activity_monthly():
    assert infer_activity("Join us monthly for AI talks") == "monthly"


def test_infer_activity_unknown():
    assert infer_activity("Tech conference and networking evening") is None


def test_normalize_url_strips_utm():
    url = "https://meetup.com/event/123?utm_source=email&utm_campaign=test"
    assert "utm_source" not in (normalize_url(url) or "")


def test_normalize_url_https_upgrade():
    url = "http://meetup.com/event/123"
    assert (normalize_url(url) or "").startswith("https://")
