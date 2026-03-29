"""
Seed the keyword table in the SQLite DB from the full keyword taxonomy.

Run once before collecting, or any time you want the keyword table to
reflect the current taxonomy in keywords.py:

    python -m community_collector.seed_keywords
    python -m community_collector.seed_keywords --db-path /path/to/custom.db
"""
from __future__ import annotations
import argparse
import sqlite3
from community_collector.config import DB_PATH
from community_collector.keywords import (
    TOPIC_KEYWORDS,
    FORMAT_KEYWORDS,
    AUDIENCE_KEYWORDS,
    VIBE_KEYWORDS,
    LOCATION_KEYWORDS,
    ALL_TAGS,
)
from community_collector.persistence import init_db


# Long-form descriptions for well-known tags (shown in UI / recommendations)
_LONG_DESCRIPTIONS: dict[str, str] = {
    "ai":               "Artificial Intelligence, Machine Learning, LLMs, GenAI",
    "data_science":     "Data Science, Analytics, Data Engineering",
    "python":           "Python programming and ecosystem",
    "open_source":      "Open source software, FOSS communities, GitHub projects",
    "cloud":            "Cloud computing, DevOps, Kubernetes, AWS/Azure/GCP",
    "cybersecurity":    "Cybersecurity, infosec, CTF, penetration testing",
    "blockchain":       "Blockchain, crypto, Web3, DeFi",
    "maker":            "Maker/hardware: Arduino, Raspberry Pi, 3D printing, robotics",
    "startup":          "Startups, founders, entrepreneurship, venture",
    "design":           "UX/UI design, product design, graphic design",
    "gaming":           "Gaming, game development, esports, game jams",
    "social_coding":    "Coding meetups, hackathons, pair programming",
    "music":            "Music events, concerts, DJs, live performances",
    "art":              "Art galleries, exhibitions, visual arts",
    "fitness":          "Fitness, run clubs, yoga, sport",
    "wellness":         "Wellness, meditation, mindfulness",
    "networking":       "Professional networking, mixers",
    "community":        "Community building, volunteering, grassroots",
    "workshop":         "Workshops, hands-on training sessions",
    "talk":             "Talks, lectures, presentations",
    "hackathon":        "Hackathons, build weekends, hack days",
    "demo_night":       "Demo nights, show-and-tell, showcases",
    "conference":       "Conferences, summits, symposia",
    "coworking":        "Coworking sessions, open studio, office hours",
    "social":           "Casual social gatherings and hangouts",
    "barcamp":          "Barcamps, unconferences, open space events",
    "beginner_friendly": "Welcoming to newcomers and beginners",
    "newcomer_friendly": "Welcoming to people new to the city or community",
    "newcomer_city":    "Specifically for people new to the city",
    "after_work":       "Evening events, after-work meetups",
    "english_friendly": "Events in or friendly to English speakers",
    "lgbtq_friendly":   "LGBTQ+ inclusive events and communities",
    "grassroots":       "Independently organised, community-driven, non-corporate",
    "free":             "Free admission / no cost",
    "paid":             "Paid ticket or registration fee",
    "online":           "Virtual / online event",
    "in_person":        "In-person attendance",
    "language_exchange": "Language exchange, tandem, polyglot meetups",
}


def seed(db_path: str) -> int:
    """
    Insert all known tags into the keyword table.
    Uses INSERT OR IGNORE so existing rows are never overwritten.
    Returns the number of newly inserted rows.
    """
    init_db(db_path)
    inserted = 0

    with sqlite3.connect(db_path) as conn:
        for tag in ALL_TAGS:
            long_desc = _LONG_DESCRIPTIONS.get(tag)
            cur = conn.execute(
                "INSERT OR IGNORE INTO keyword (short, long) VALUES (?, ?)",
                (tag, long_desc),
            )
            inserted += cur.rowcount
        conn.commit()

    return inserted


def main() -> None:
    p = argparse.ArgumentParser(description="Seed keyword table from taxonomy")
    p.add_argument("--db-path", default=str(DB_PATH), help="Path to SQLite DB")
    args = p.parse_args()

    count = seed(args.db_path)
    print(f"Seeded {count} new keywords into {args.db_path}")
    print(f"Total taxonomy size: {len(ALL_TAGS)} tags")


if __name__ == "__main__":
    main()
