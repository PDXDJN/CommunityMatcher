"""
BerlinCommunitiesAdapter — curated static list of known Berlin tech/maker/community orgs.

This adapter supplements the Playwright-based scrapers with a hand-curated set of
established Berlin communities that are unlikely to appear in standard event searches
(hackerspace residencies, grassroots orgs, long-running groups).

It does NOT scrape — it returns structured records directly from a maintained list.
This means results are immediately available without a browser and never go stale
from DOM changes. Update the list as communities evolve.

Each entry follows the CommunityEventRecord schema used by the other adapters.
"""
from __future__ import annotations
from datetime import datetime, timezone

from community_collector.adapters.base import BaseSourceAdapter
from community_collector.models import CommunityEventRecord

_NOW = datetime.now(timezone.utc).isoformat()

# Curated list: established Berlin tech/maker/community organizations.
# Fields: title, url, description, tags, topic_signals, format_signals,
#         audience_signals, vibe_signals, activity
_COMMUNITIES: list[dict] = [
    {
        "title": "c-base — Berliner Hackerspace",
        "url": "https://c-base.org",
        "description": (
            "One of the world's oldest hackerspaces, located in Mitte. "
            "Open nights, workshops, maker projects, radio, art, and community. "
            "Newcomers welcome at public events."
        ),
        "topic_signals": ["maker", "cybersecurity", "tech", "social_coding"],
        "format_signals": ["workshop", "social", "coworking", "hackathon"],
        "audience_signals": ["newcomer_city", "english_friendly"],
        "vibe_signals": ["grassroots", "technical", "casual"],
        "activity": "weekly",
    },
    {
        "title": "Chaos Computer Club Berlin (CCC Berlin)",
        "url": "https://berlin.ccc.de",
        "description": (
            "Berlin chapter of the Chaos Computer Club. Hacker culture, digital rights, "
            "security research, privacy activism. Regular events at the Chaos West space."
        ),
        "topic_signals": ["cybersecurity", "tech", "blockchain"],
        "format_signals": ["talk", "workshop", "barcamp"],
        "audience_signals": ["technical", "english_friendly"],
        "vibe_signals": ["grassroots", "technical"],
        "activity": "monthly",
    },
    {
        "title": "OpenTechSchool Berlin",
        "url": "https://www.opentechschool.org/berlin",
        "description": (
            "Free, inclusive tech education for all skill levels. "
            "Python, JavaScript, data science, and more. "
            "Particularly welcoming to beginners and underrepresented groups."
        ),
        "topic_signals": ["python", "data_science", "tech", "social_coding"],
        "format_signals": ["workshop", "talk"],
        "audience_signals": ["beginner_friendly", "newcomer_city", "english_friendly"],
        "vibe_signals": ["grassroots", "casual", "technical"],
        "activity": "monthly",
    },
    {
        "title": "Rails Girls Berlin",
        "url": "https://railsgirls.com/berlin",
        "description": (
            "Free workshops teaching Ruby on Rails and web development, "
            "aimed at women and non-binary people. Beginner-friendly, "
            "welcoming community with coaching from experienced developers."
        ),
        "topic_signals": ["design", "social_coding", "tech"],
        "format_signals": ["workshop"],
        "audience_signals": ["beginner_friendly", "newcomer_city", "english_friendly"],
        "vibe_signals": ["grassroots", "casual"],
        "activity": "recurring",
    },
    {
        "title": "PyLadies Berlin",
        "url": "https://www.meetup.com/PyLadies-Berlin/",
        "description": (
            "Berlin chapter of PyLadies — an international mentorship group focused on "
            "helping more women become active participants and leaders in the Python "
            "open-source community."
        ),
        "topic_signals": ["python", "data_science", "social_coding"],
        "format_signals": ["workshop", "talk", "social"],
        "audience_signals": ["beginner_friendly", "english_friendly"],
        "vibe_signals": ["grassroots", "casual", "technical"],
        "activity": "monthly",
    },
    {
        "title": "Berlin Buzzwords (conference)",
        "url": "https://berlinbuzzwords.de",
        "description": (
            "Annual open source conference on large-scale data, cloud, search, and AI. "
            "Community-run, mix of expert talks and workshops. Usually in June."
        ),
        "topic_signals": ["data_science", "ai", "cloud", "tech"],
        "format_signals": ["conference", "workshop", "talk"],
        "audience_signals": ["technical", "english_friendly"],
        "vibe_signals": ["technical", "grassroots"],
        "activity": "one-off",
    },
    {
        "title": "GameDevBerlin",
        "url": "https://gamedevberlin.com",
        "description": (
            "Berlin's game developer community. Meetups, talks, and networking for "
            "indie devs, artists, and game industry professionals. "
            "Regular social events and playtests."
        ),
        "topic_signals": ["gaming", "design", "tech"],
        "format_signals": ["social", "talk", "demo_night"],
        "audience_signals": ["english_friendly", "newcomer_city"],
        "vibe_signals": ["casual", "technical", "creative"],
        "activity": "monthly",
    },
    {
        "title": "Jugend Hackt Berlin",
        "url": "https://jugendhackt.org/events/berlin/",
        "description": (
            "Tech events for young people aged 12-18. Hackathons, workshops, "
            "social coding, and civic tech. Run by volunteers."
        ),
        "topic_signals": ["maker", "tech", "social_coding"],
        "format_signals": ["hackathon", "workshop"],
        "audience_signals": ["beginner_friendly", "newcomer_city"],
        "vibe_signals": ["grassroots", "casual"],
        "activity": "recurring",
    },
    {
        "title": "Berlin Startup Network",
        "url": "https://www.meetup.com/Berlin-Startup-Network/",
        "description": (
            "Networking events for founders, investors, and startup employees in Berlin. "
            "Monthly meetups with talks, pitches, and casual networking."
        ),
        "topic_signals": ["startup", "tech", "networking"],
        "format_signals": ["networking", "talk", "social"],
        "audience_signals": ["english_friendly", "career_oriented"],
        "vibe_signals": ["career_oriented", "casual"],
        "activity": "monthly",
    },
    {
        "title": "Quantified Self Berlin",
        "url": "https://www.meetup.com/Quantified-Self-Berlin/",
        "description": (
            "Self-tracking, biohacking, and personal data community. "
            "Show-and-tell format: members share what they measure and why."
        ),
        "topic_signals": ["data_science", "fitness", "wellness", "tech"],
        "format_signals": ["talk", "social"],
        "audience_signals": ["english_friendly", "newcomer_city"],
        "vibe_signals": ["technical", "casual"],
        "activity": "monthly",
    },
    {
        "title": "Code for Berlin (Open Knowledge Foundation)",
        "url": "https://codefor.de/berlin/",
        "description": (
            "Civic tech and open data community. Regular hack nights building tools "
            "for the public good. Open to coders, designers, and civic thinkers."
        ),
        "topic_signals": ["social_coding", "tech", "data_science"],
        "format_signals": ["hackathon", "workshop", "social"],
        "audience_signals": ["beginner_friendly", "newcomer_city", "english_friendly"],
        "vibe_signals": ["grassroots", "casual", "technical"],
        "activity": "weekly",
    },
    {
        "title": "Maker Faire Berlin",
        "url": "https://makerfaire.com/berlin/",
        "description": (
            "Annual celebration of invention, creativity, and resourcefulness. "
            "3D printing, electronics, robotics, crafts, and DIY science. "
            "Great for maker and hardware enthusiasts."
        ),
        "topic_signals": ["maker", "tech", "design"],
        "format_signals": ["conference", "workshop", "social"],
        "audience_signals": ["beginner_friendly", "newcomer_city", "english_friendly"],
        "vibe_signals": ["grassroots", "creative", "casual"],
        "activity": "one-off",
    },
]


class BerlinCommunitiesAdapter(BaseSourceAdapter):
    source_name = "berlin_curated"

    async def collect(self, request: dict) -> list[dict]:
        """
        Return curated Berlin community records matching any of the request's
        search_terms or category_filters. If no filters are specified, return all.

        No browser is launched — this is a static lookup.
        """
        terms = [t.lower() for t in (request.get("search_terms") or [])]
        categories = [c.lower() for c in (request.get("category_filters") or [])]

        results: list[dict] = []
        for community in _COMMUNITIES:
            if not terms and not categories:
                results.append(community)
                continue

            # Match against title, description, and any signal list
            all_signals = (
                community.get("topic_signals", [])
                + community.get("format_signals", [])
                + community.get("audience_signals", [])
                + community.get("vibe_signals", [])
            )
            combined_text = (
                community["title"].lower()
                + " "
                + community["description"].lower()
                + " "
                + " ".join(all_signals)
            )

            matched = (
                any(term in combined_text for term in terms)
                or any(cat in combined_text for cat in categories)
            )
            if matched:
                results.append(community)

        return results


def records_from_curated(request: dict) -> list[CommunityEventRecord]:
    """
    Synchronous helper: run the curated adapter and return normalized records.
    Used by the collector orchestrator.
    """
    import asyncio

    adapter = BerlinCommunitiesAdapter()
    raw = asyncio.run(adapter.collect(request))

    records: list[CommunityEventRecord] = []
    for item in raw:
        records.append(
            CommunityEventRecord(
                source="berlin_curated",
                source_url=item["url"],
                canonical_url=item["url"],
                title=item["title"],
                description=item["description"],
                activity=item.get("activity", "recurring"),
                tags=(
                    item.get("topic_signals", [])
                    + item.get("format_signals", [])
                    + item.get("audience_signals", [])
                    + item.get("vibe_signals", [])
                ),
                topic_signals=item.get("topic_signals", []),
                format_signals=item.get("format_signals", []),
                audience_signals=item.get("audience_signals", []),
                vibe_signals=item.get("vibe_signals", []),
                city="Berlin",
                country="Germany",
                is_online=False,
                extraction_timestamp=_NOW,
            )
        )
    return records
