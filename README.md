# Scrape-Bsides

Python scraper for the **BSides Seattle 2026** conference schedule.

## Conference Overview

- **Dates:** February 27–28, 2026
- **Location:** Seattle, WA
- **Website:** https://www.bsidesseattle.com/
- **Schedule Source:** https://bsides-seattle-2026.sessionize.com/schedule
- **Total sessions:** 72
- **Tracks:** Track 1, Track 2, Track 3, Track 4, Track 5
- **Topics:** Bridging Divides, Lurking Dangers, Real-World Chronicles, Uncharted Territory

## Usage

```bash
# Install dependencies
pip install playwright beautifulsoup4
playwright install chromium

# Run the scraper
python scrape_bsides.py
```

This produces `bsides_seattle_2026_schedule.md` — a Markdown file with the full schedule including session titles, speakers, descriptions, times, tracks, and topics. Upload it to Google Drive and query it with Claude for personalized session recommendations.
