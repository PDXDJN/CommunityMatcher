import pytest
from community_collector.models import CommunityEventRecord


def test_record_requires_source_and_url_and_title():
    with pytest.raises(Exception):
        CommunityEventRecord()


def test_record_minimal_valid():
    rec = CommunityEventRecord(
        source="meetup",
        source_url="https://meetup.com/test",
        title="Berlin Python Meetup",
    )
    assert rec.source == "meetup"
    assert rec.tags == []
    assert rec.cost_factor is None
    assert rec.extraction_timestamp != ""


def test_record_title_stripped():
    rec = CommunityEventRecord(
        source="eventbrite",
        source_url="https://eventbrite.com/e/123",
        title="  AI Hackathon  ",
    )
    assert rec.title == "AI Hackathon"


def test_record_empty_title_rejected():
    with pytest.raises(Exception):
        CommunityEventRecord(
            source="meetup",
            source_url="https://meetup.com/test",
            title="   ",
        )


def test_record_serializes_to_dict():
    rec = CommunityEventRecord(
        source="luma",
        source_url="https://lu.ma/event/abc",
        title="Startup Drinks Berlin",
        tags=["networking", "startup"],
    )
    d = rec.model_dump()
    assert d["tags"] == ["networking", "startup"]
    assert d["source"] == "luma"
