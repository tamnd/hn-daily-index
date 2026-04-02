"""
hn-daily-index: Fetch today's top 10 Hacker News stories and append them
to a cumulative README.md organized by date.

Data is stored as data/YYYY/MM/DD.json. The README is rebuilt from scratch
each run, covering all years present in the data directory.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
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
# Data I/O  (data/YYYY/MM/DD.json)
# ---------------------------------------------------------------------------


def _date_to_path(d: date) -> Path:
    return DATA_DIR / str(d.year) / f"{d.month:02d}" / f"{d.day:02d}.json"


def _save_daily_json(date_str: str, stories: list[dict]) -> None:
    d = date.fromisoformat(date_str)
    path = _date_to_path(d)
    path.parent.mkdir(parents=True, exist_ok=True)
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
    path.write_text(json.dumps(records, indent=2) + "\n")


def _scan_available() -> dict[str, list[dict]]:
    """Scan data/ tree and return {YYYY-MM-DD: stories} for all days."""
    result: dict[str, list[dict]] = {}
    if not DATA_DIR.exists():
        return result
    for json_file in DATA_DIR.glob("*/*/*.json"):
        # data/YYYY/MM/DD.json
        try:
            day = int(json_file.stem)
            month = int(json_file.parent.name)
            year = int(json_file.parent.parent.name)
            ds = f"{year:04d}-{month:02d}-{day:02d}"
            result[ds] = json.loads(json_file.read_text())
        except (ValueError, json.JSONDecodeError):
            continue
    return result


# ---------------------------------------------------------------------------
# Migrate flat data/ files to nested structure
# ---------------------------------------------------------------------------


def _migrate_flat_data() -> None:
    """Move any data/YYYY-MM-DD.json files into data/YYYY/MM/DD.json."""
    for f in DATA_DIR.glob("????-??-??.json"):
        try:
            d = date.fromisoformat(f.stem)
            dest = _date_to_path(d)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                f.rename(dest)
            else:
                f.unlink()
        except ValueError:
            continue


# ---------------------------------------------------------------------------
# README generation
# ---------------------------------------------------------------------------

HEADER = """\
<div align="center">

<img src="https://news.ycombinator.com/y18.svg" width="80">

# HN Daily Index

</div>

A daily archive of the top 10 stories on [Hacker News](https://news.ycombinator.com), organized by date.

> Thanks to [Hacker News](https://news.ycombinator.com) by [Y Combinator](https://www.ycombinator.com) for the [API](https://github.com/HackerNews/API), and to Colin Percival's [Hacker News Daily](https://www.daemonology.net/hn-daily/) for the historical archive going back to 2010.

## Contents

"""


def _all_dates_in_year(year: int) -> list[date]:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    today = date.today()
    if year == today.year:
        end = today
    dates = []
    d = start
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)
    return dates


def _render_month_calendar(
    month_dates: list[date], available: set[str]
) -> list[str]:
    """Render a month as a compact calendar table."""
    lines = []
    lines.append("| Mon | Tue | Wed | Thu | Fri | Sat | Sun |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")

    first = month_dates[0]
    row: list[str] = [""] * first.weekday()

    for d in month_dates:
        ds = d.isoformat()
        day_num = str(d.day)
        if ds in available:
            row.append(f"[**{day_num}**](#{ds})")
        else:
            row.append(day_num)

        if len(row) == 7:
            lines.append("| " + " | ".join(row) + " |")
            row = []

    if row:
        row.extend([""] * (7 - len(row)))
        lines.append("| " + " | ".join(row) + " |")

    return lines


def _generate_readme() -> str:
    DATA_DIR.mkdir(exist_ok=True)

    available_data = _scan_available()
    available = set(available_data.keys())

    if not available:
        return HEADER + "*No stories yet. Run `uv run hn-daily-index` to fetch today's top 10.*\n"

    # Determine all years that have data
    years_with_data = sorted({date.fromisoformat(ds).year for ds in available}, reverse=True)
    # Also include current year
    current_year = date.today().year
    if current_year not in years_with_data:
        years_with_data = [current_year] + years_with_data

    lines = [HEADER]

    # Recent days quick-jump (last 7 days with data)
    recent = sorted(available, reverse=True)[:7]
    if recent:
        links = [
            f"[{date.fromisoformat(ds).strftime('%b %d')}](#{ds})"
            for ds in recent
        ]
        lines.append("Recent: " + " | ".join(links))
        lines.append("")

    # Year-level sections
    for year in years_with_data:
        all_dates = _all_dates_in_year(year)
        total_days = len(all_dates)
        covered = sum(1 for d in all_dates if d.isoformat() in available)

        lines.append(f"### {year} ({covered}/{total_days} days)")
        lines.append("")

        # Group by month, most recent first
        months: dict[str, list[date]] = {}
        for d in all_dates:
            key = d.strftime("%Y-%m")
            months.setdefault(key, []).append(d)

        month_keys = sorted(months.keys(), reverse=True)

        for month_key in month_keys:
            month_dates = months[month_key]
            month_label = month_dates[0].strftime("%B")
            month_covered = sum(1 for d in month_dates if d.isoformat() in available)
            month_total = len(month_dates)

            lines.append(f"**{month_label}** ({month_covered}/{month_total})")
            lines.append("")
            lines.extend(_render_month_calendar(month_dates, available))
            lines.append("")

    lines.append("---")
    lines.append("")

    # Render each day with data, most recent first
    for ds in sorted(available, reverse=True):
        stories = available_data[ds]
        d = date.fromisoformat(ds)
        weekday = d.strftime("%A")

        lines.append(f"## {ds}")
        lines.append("")
        lines.append(f"*{weekday}*")
        lines.append("")

        for story in stories:
            lines.append(_format_story(story["rank"], story))

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
# Per-month README: data/YYYY/MM/README.md
# ---------------------------------------------------------------------------


def _generate_month_readme(
    year: int, month: int, available_data: dict[str, list[dict]]
) -> str:
    month_name = date(year, month, 1).strftime("%B %Y")
    lines = [f"# {month_name}", ""]
    lines.append(
        f"Top 10 Hacker News stories for each day in {month_name}."
    )
    lines.append("")

    # Collect days in this month that have data
    days = sorted(
        [ds for ds in available_data if ds.startswith(f"{year:04d}-{month:02d}-")],
        reverse=True,
    )

    if not days:
        lines.append("*No data yet.*")
        lines.append("")
        return "\n".join(lines)

    # TOC
    for ds in days:
        d = date.fromisoformat(ds)
        lines.append(f"- [{ds} ({d.strftime('%A')})](#{ds})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Each day
    for ds in days:
        d = date.fromisoformat(ds)
        stories = available_data[ds]
        lines.append(f"## {ds}")
        lines.append("")
        lines.append(f"*{d.strftime('%A')}*")
        lines.append("")
        for story in stories:
            lines.append(_format_story(story["rank"], story))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-year README: data/YYYY/README.md
# ---------------------------------------------------------------------------


def _generate_year_readme(
    year: int, available_data: dict[str, list[dict]]
) -> str:
    lines = [f"# {year}", ""]
    lines.append(
        f"Top 10 Hacker News stories for each day in {year}."
    )
    lines.append("")

    # Group by month
    month_days: dict[int, list[str]] = {}
    for ds in available_data:
        d = date.fromisoformat(ds)
        if d.year == year:
            month_days.setdefault(d.month, []).append(ds)

    if not month_days:
        lines.append("*No data yet.*")
        lines.append("")
        return "\n".join(lines)

    # TOC linking to monthly READMEs
    for m in sorted(month_days.keys(), reverse=True):
        month_name = date(year, m, 1).strftime("%B")
        count = len(month_days[m])
        lines.append(f"- [{month_name}]({m:02d}/) ({count} days)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Inline all stories, most recent first
    all_days = sorted(
        [ds for ds in available_data if date.fromisoformat(ds).year == year],
        reverse=True,
    )
    for ds in all_days:
        d = date.fromisoformat(ds)
        stories = available_data[ds]
        lines.append(f"## {ds}")
        lines.append("")
        lines.append(f"*{d.strftime('%A')}*")
        lines.append("")
        for story in stories:
            lines.append(_format_story(story["rank"], story))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generate all sub-READMEs
# ---------------------------------------------------------------------------


def _generate_sub_readmes(available_data: dict[str, list[dict]]) -> None:
    """Generate data/YYYY/README.md and data/YYYY/MM/README.md for all data."""
    # Group by year and month
    years: set[int] = set()
    year_months: set[tuple[int, int]] = set()
    for ds in available_data:
        d = date.fromisoformat(ds)
        years.add(d.year)
        year_months.add((d.year, d.month))

    for y in years:
        readme = _generate_year_readme(y, available_data)
        path = DATA_DIR / str(y) / "README.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(readme)

    for y, m in year_months:
        readme = _generate_month_readme(y, m, available_data)
        path = DATA_DIR / str(y) / f"{m:02d}" / "README.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(readme)


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

    # Migrate any old flat files
    _migrate_flat_data()

    print("Saving daily JSON...", file=sys.stderr)
    _save_daily_json(today, stories)

    print("Generating READMEs...", file=sys.stderr)
    readme = _generate_readme()
    README_FILE.write_text(readme)

    available_data = _scan_available()
    _generate_sub_readmes(available_data)

    print(f"Done! {README_FILE}", file=sys.stderr)
