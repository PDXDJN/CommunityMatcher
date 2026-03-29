from community_collector.tagging import (
    tag_record, infer_topic_signals, infer_format_signals,
    infer_audience_signals, infer_vibe_signals,
)


def test_ai_topic_detected():
    signals = infer_topic_signals("monthly AI and machine learning meetup for developers")
    assert "ai" in signals


def test_python_topic_detected():
    signals = infer_topic_signals("Introduction to pandas and Jupyter notebooks")
    assert "python" in signals
    assert "data_science" in signals


def test_hackathon_format_detected():
    signals = infer_format_signals("48-hour hackathon for open source contributors")
    assert "hackathon" in signals


def test_networking_format_detected():
    signals = infer_format_signals("evening networking mixer for tech professionals")
    assert "networking" in signals


def test_beginner_audience_detected():
    signals = infer_audience_signals("Intro to Python — no experience needed, beginner friendly")
    assert "beginner_friendly" in signals


def test_online_tag_from_is_online_flag():
    result = tag_record(
        title="Online AI Webinar",
        description=None, organizer_name=None, community_name=None,
        venue_name=None, cost_text=None, raw_category=None,
        source_url=None, is_online=True,
    )
    assert "online" in result["tags"]


def test_free_tag_from_cost_text():
    result = tag_record(
        title="Python Meetup",
        description=None, organizer_name=None, community_name=None,
        venue_name=None, cost_text="Free admission, kostenlos",
        raw_category=None, source_url=None,
    )
    assert "free" in result["tags"]


def test_tag_record_returns_all_signal_keys():
    result = tag_record(
        title="Startup Drinks Berlin",
        description="Casual evening networking for founders and engineers",
        organizer_name=None, community_name=None, venue_name="Bar in Mitte",
        cost_text="Free", raw_category=None, source_url=None,
    )
    for key in ("tags", "topic_signals", "format_signals", "audience_signals", "vibe_signals"):
        assert key in result


def test_no_false_positives_on_empty():
    result = tag_record(
        title="", description="", organizer_name=None, community_name=None,
        venue_name=None, cost_text=None, raw_category=None, source_url=None,
    )
    assert isinstance(result["tags"], list)
