#!/usr/bin/env python3
"""
BSides Seattle 2026 Schedule Scraper

Scrapes the full conference schedule from bsides-seattle-2026.sessionize.com
including session titles, speakers, descriptions, times, tracks, and topics.

Outputs a Markdown file suitable for uploading to Google Drive and querying
with Claude or other AI assistants.

Requirements:
    pip install playwright beautifulsoup4
    playwright install chromium
"""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

BASE_URL = "https://bsides-seattle-2026.sessionize.com"
SCHEDULE_DAYS = [
    ("Friday, February 27, 2026", f"{BASE_URL}/schedule/day/20260227"),
    ("Saturday, February 28, 2026", f"{BASE_URL}/schedule/day/20260228"),
]

# Sessions to skip (non-content entries)
SKIP_TITLES = {
    "Room Closed", "Room Hold", "Lunch", "Evening Social",
    "Closing", "Room closed",
}


async def scrape_schedule_day(page, day_name: str, day_url: str) -> list[dict]:
    """Scrape all sessions from a single day's schedule page."""
    print(f"  Fetching schedule for {day_name}...")
    await page.goto(day_url, wait_until="networkidle", timeout=30000)
    # Wait for Vue.js to render sessions — retry up to 15 seconds
    for _ in range(15):
        await page.wait_for_timeout(1000)
        count = await page.locator("article.c-session").count()
        if count > 0:
            break
    await page.wait_for_timeout(1000)  # extra settle time

    html = await page.content()
    soup = BeautifulSoup(html, "html.parser")

    sessions = []

    # Sessionize renders sessions as <article class="c-session"> elements
    articles = soup.find_all("article", class_="c-session")

    for article in articles:
        # Title
        title_el = article.find(class_="c-session__title")
        if not title_el:
            continue
        title_link = title_el.find("a")
        title = title_el.get_text(strip=True)
        if title in SKIP_TITLES:
            continue

        href = title_link.get("href", "") if title_link else ""
        session_url = (href if href.startswith("http") else BASE_URL + href) if href else ""

        # Time
        time_el = article.find(class_="c-session__time")
        time_str = ""
        if time_el:
            raw_time = time_el.get_text(strip=True)
            # Extract just the time portion: "Today at 10:00 AM" -> "10:00 AM"
            m = re.search(r"(\d{1,2}:\d{2}\s*[AP]M)", raw_time)
            time_str = m.group(1) if m else raw_time

        # Duration
        dur_el = article.find(class_="c-session__duration")
        duration = dur_el.get_text(strip=True) if dur_el else ""

        # Track / Room
        loc_el = article.find(class_="c-session__location")
        track = loc_el.get_text(strip=True) if loc_el else ""

        # Speakers
        speaker_els = article.find_all(class_="c-session__speaker")
        speakers = [s.get_text(strip=True) for s in speaker_els]
        speaker = ", ".join(speakers)

        # Tags (topic + session length)
        tag_els = article.find_all(class_="c-session__tag")
        topic = ""
        for tag in tag_els:
            tag_text = tag.get_text(strip=True)
            if not tag_text.startswith("I'm planning"):
                topic = tag_text

        sessions.append({
            "title": title,
            "speaker": speaker,
            "time": time_str,
            "duration": duration,
            "track": track,
            "day": day_name,
            "url": session_url,
            "topic": topic,
            "description": "",  # filled in from detail pages
        })

    print(f"    Found {len(sessions)} sessions")
    return sessions


async def scrape_session_detail(page, session: dict) -> dict:
    """Scrape the full description from an individual session page."""
    if not session["url"]:
        return session
    try:
        await page.goto(session["url"], wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(2000)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # Try known Sessionize detail page classes
        desc_el = (
            soup.find(class_="c-session-item__description")
            or soup.find(class_="c-session-item__content")
        )
        if desc_el:
            session["description"] = desc_el.get_text(" ", strip=True)
            return session

        # Fallback: extract from main content area
        main_el = soup.find("main") or soup.find(class_="l-content") or soup.body
        if not main_el:
            return session

        text = main_el.get_text("\n", strip=True)
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        desc_lines = []
        capture = False
        for line in lines:
            if session["title"] in line and not capture:
                capture = True
                continue
            if capture:
                # Skip UI / metadata lines
                if line in ("Favorite", "Remove from favorites"):
                    continue
                if re.match(r"(Today|Tomorrow|Now|.*?at \d+:\d+\s*[AP]M)", line):
                    continue
                if re.match(r"^\d+\s*min$", line):
                    continue
                if re.match(r"^Track\s+\d+$", line):
                    continue
                if session["speaker"] and line == session["speaker"]:
                    continue
                # Stop at known section boundaries
                if any(marker in line for marker in [
                    "CONCURRENT SESSIONS", "Additional Links",
                    "Topic", "Session Length",
                ]):
                    break
                # Skip UI noise
                if any(noise in line for noise in [
                    "Scan QR code", "Code can be found",
                    "bla bla", "Cancel",
                ]):
                    continue
                desc_lines.append(line)

        if desc_lines:
            desc = " ".join(desc_lines)
            # Clean trailing UI artifacts
            desc = re.sub(r"\s*Scan QR code.*$", "", desc)
            session["description"] = desc.strip()

    except Exception as e:
        print(f"    Warning: Could not fetch details for '{session['title']}': {e}")

    return session


async def main():
    output_dir = Path(__file__).parent
    output_file = output_dir / "bsides_seattle_2026_schedule.md"

    print("=" * 60)
    print("BSides Seattle 2026 Schedule Scraper")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        # --- Scrape schedule for each day ---
        all_sessions = []
        for day_name, day_url in SCHEDULE_DAYS:
            sessions = await scrape_schedule_day(page, day_name, day_url)
            all_sessions.extend(sessions)

        print(f"\nTotal sessions found: {len(all_sessions)}")

        if not all_sessions:
            print("ERROR: No sessions found. The website structure may have changed.")
            await browser.close()
            sys.exit(1)

        # --- Scrape individual session details for descriptions ---
        print("\nFetching session descriptions (this may take a few minutes)...")
        for i, session in enumerate(all_sessions, 1):
            print(f"  [{i}/{len(all_sessions)}] {session['title'][:60]}...")
            await scrape_session_detail(page, session)
            await page.wait_for_timeout(500)  # be polite to the server

        await browser.close()

    # --- Sort sessions by day and time ---
    def time_sort_key(s):
        t = s.get("time", "")
        if not t or t == "(in progress)":
            return "99:99"
        try:
            return datetime.strptime(t.strip(), "%I:%M %p").strftime("%H:%M")
        except ValueError:
            return "99:99"

    day_order = {d[0]: i for i, d in enumerate(SCHEDULE_DAYS)}
    all_sessions.sort(
        key=lambda s: (
            day_order.get(s["day"], 99),
            time_sort_key(s),
            s.get("track", ""),
        )
    )

    # --- Generate Markdown output ---
    print(f"\nWriting schedule to {output_file}...")

    lines = []
    lines.append("# BSides Seattle 2026 — Full Conference Schedule\n")
    lines.append("**Conference Dates:** February 27–28, 2026")
    lines.append("**Location:** Seattle, WA")
    lines.append("**Website:** https://www.bsidesseattle.com/")
    lines.append("**Schedule Source:** https://bsides-seattle-2026.sessionize.com/schedule")
    lines.append(f"**Scraped:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary stats
    topics = set(s["topic"] for s in all_sessions if s["topic"])
    tracks = set(s["track"] for s in all_sessions if s["track"])
    lines.append("## Conference Overview\n")
    lines.append(f"- **Total sessions:** {len(all_sessions)}")
    lines.append(f"- **Tracks:** {', '.join(sorted(tracks)) if tracks else 'N/A'}")
    lines.append(f"- **Topics:** {', '.join(sorted(topics)) if topics else 'N/A'}")
    lines.append("")
    lines.append("---")
    lines.append("")

    current_day = None
    current_time = None

    for session in all_sessions:
        # Day header
        if session["day"] != current_day:
            current_day = session["day"]
            current_time = None
            lines.append(f"## {current_day}\n")

        # Time slot header
        time_display = session.get("time") or "TBD"
        if time_display != current_time:
            current_time = time_display
            lines.append(f"### {current_time}\n")

        # Session entry
        lines.append(f"#### {session['title']}\n")

        meta_parts = []
        if session.get("speaker"):
            meta_parts.append(f"**Speaker(s):** {session['speaker']}")
        if session.get("track"):
            meta_parts.append(f"**Room:** {session['track']}")
        if session.get("duration"):
            meta_parts.append(f"**Duration:** {session['duration']}")
        if session.get("topic"):
            meta_parts.append(f"**Topic:** {session['topic']}")

        for part in meta_parts:
            lines.append(f"- {part}")
        if meta_parts:
            lines.append("")

        if session.get("description"):
            lines.append(session["description"])
            lines.append("")

        if session.get("url"):
            lines.append(f"[View session details]({session['url']})")
            lines.append("")

        lines.append("---\n")

    # Write the file
    output_file.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nDone! Schedule saved to: {output_file}")
    print(f"Total sessions: {len(all_sessions)}")
    print(f"Sessions with descriptions: {sum(1 for s in all_sessions if s['description'])}")
    print(
        "\nUpload this file to Google Drive and use Claude to get personalized "
        "session recommendations!"
    )


if __name__ == "__main__":
    asyncio.run(main())
