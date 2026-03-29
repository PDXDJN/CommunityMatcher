"""
Web entry point for Community Matcher.

Usage:
    python web_main.py
    # or
    uvicorn community_matcher.web_app:app --reload
"""
import sys

import uvicorn

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

if __name__ == "__main__":
    print("Starting Community Matcher at http://localhost:8000")
    uvicorn.run(
        "community_matcher.web_app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
