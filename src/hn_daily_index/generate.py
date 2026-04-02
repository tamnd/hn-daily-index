"""
hn-daily-index: Fetch today's top 10 Hacker News stories and append them
to a cumulative README.md organized by date.

The README is append-only: each run adds today's section without touching
past entries. This keeps the full history as a growing archive.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HN_API = "https://hacker-news.firebaseio.com/v0"
TOP_N = 10
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
README_FILE = PROJECT_ROOT / "README.md"
DATA_DIR = PROJECT_ROOT / "data"

# ---------------------------------------------------------------------------
# Fetch stories from Hacker News API
# ---------------------------------------------------------------------------


async def _fetch_top_stories(client: httpx.AsyncClient) -> list[int]:
    resp = await client.get(f"{HN_API}/topstories.json", timeout=15)
    resp.raise_for_status()
    return resp.json()[:TOP_N]


async def _fetch_item(client: httpx.AsyncClient, item_id: int) -> dict:
    resp = await client.get(f"{HN_API}/item/{item_id}.json", timeout=15)
    resp.raise_for_status()
    return resp.json()


async def _fetch_today_stories() -> list[dict]:
    async with httpx.AsyncClient() as client:
        top_ids = await _fetch_top_stories(client)
        stories = await asyncio.gather(
            *(_fetch_item(client, sid) for sid in top_ids)
        )
    return [s for s in stories if s and s.get("type") == "story"]


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------


def _hn_link(story_id: int) -> str:
    return f"https://news.ycombinator.com/item?id={story_id}"


def _format_score(score: int) -> str:
    if score >= 1000:
        return f"{score / 1000:.1f}k"
    return str(score)


def _format_story(rank: int, story: dict) -> str:
    title = story.get("title", "Untitled")
    url = story.get("url", "")
    score = story.get("score", 0)
    author = story.get("by", "unknown")
    comments = story.get("descendants", 0)
    story_id = story.get("id", 0)
    hn_url = _hn_link(story_id)

    if url:
        # Extract domain for display
        domain = re.sub(r"^https?://(?:www\.)?", "", url).split("/")[0]
        title_link = f"[{title}]({url})"
        source = f" ({domain})"
    else:
        title_link = f"[{title}]({hn_url})"
        source = ""

    return (
        f"{rank}. {title_link}{source} - "
        f"{_format_score(score)} points by [{author}](https://news.ycombinator.com/user?id={author}), "
        f"[{comments} comments]({hn_url})"
    )


# ---------------------------------------------------------------------------
# Daily JSON archive
# ---------------------------------------------------------------------------


def _save_daily_json(date_str: str, stories: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    file = DATA_DIR / f"{date_str}.json"
    records = []
    for i, s in enumerate(stories, 1):
        records.append({
            "rank": i,
            "id": s.get("id"),
            "title": s.get("title", ""),
            "url": s.get("url", ""),
            "score": s.get("score", 0),
            "by": s.get("by", ""),
            "descendants": s.get("descendants", 0),
            "time": s.get("time", 0),
        })
    file.write_text(json.dumps(records, indent=2) + "\n")


# ---------------------------------------------------------------------------
# README generation
# ---------------------------------------------------------------------------

HEADER = """\
<div align="center">

<img src="https://news.ycombinator.com/y18.svg" width="80">

# HN Daily Index

</div>

A daily archive of the top 10 stories on [Hacker News](https://news.ycombinator.com), organized by date.

## Contents

"""


def _load_existing_dates() -> set[str]:
    """Parse existing README to find which dates are already present."""
    if not README_FILE.exists():
        return set()
    text = README_FILE.read_text()
    return set(re.findall(r"^## (\d{4}-\d{2}-\d{2})", text, re.MULTILINE))


def _load_daily_data(date_str: str) -> list[dict] | None:
    file = DATA_DIR / f"{date_str}.json"
    if file.exists():
        return json.loads(file.read_text())
    return None


def _generate_readme() -> str:
    """Rebuild the full README from all daily JSON files."""
    DATA_DIR.mkdir(exist_ok=True)
    json_files = sorted(DATA_DIR.glob("*.json"), reverse=True)

    if not json_files:
        return HEADER + "*No stories yet. Run `uv run hn-daily-index` to fetch today's top 10.*\n"

    lines = [HEADER]

    # Build TOC grouped by month
    dates = [f.stem for f in json_files]
    months_seen: list[str] = []
    month_dates: dict[str, list[str]] = {}
    for d in dates:
        month = d[:7]  # YYYY-MM
        if month not in month_dates:
            months_seen.append(month)
            month_dates[month] = []
        month_dates[month].append(d)

    for month in months_seen:
        month_label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
        lines.append(f"**{month_label}**")
        lines.append("")
        for d in month_dates[month]:
            weekday = datetime.strptime(d, "%Y-%m-%d").strftime("%A")
            lines.append(f"- [{d} ({weekday})](#{d})")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Render each day
    for json_file in json_files:
        date_str = json_file.stem
        stories = json.loads(json_file.read_text())
        weekday = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")

        lines.append(f"## {date_str}")
        lines.append("")
        lines.append(f"*{weekday}*")
        lines.append("")

        for story in stories:
            rank = story["rank"]
            lines.append(_format_story(rank, story))

        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(
        "Generated by [hn-daily-index](https://github.com/tamnd/hn-daily-index). "
        "Data sourced from the [Hacker News API](https://github.com/HackerNews/API)."
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    asyncio.run(_async_main())


async def _async_main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Fetching top {TOP_N} Hacker News stories for {today}...", file=sys.stderr)
    stories = await _fetch_today_stories()
    print(f"  Got {len(stories)} stories.", file=sys.stderr)

    print("Saving daily JSON...", file=sys.stderr)
    _save_daily_json(today, stories)

    print("Generating README.md...", file=sys.stderr)
    readme = _generate_readme()
    README_FILE.write_text(readme)

    print(f"Done! {README_FILE}", file=sys.stderr)
