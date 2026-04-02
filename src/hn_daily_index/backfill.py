"""
Backfill historical top HN stories from https://www.daemonology.net/hn-daily/.

That site has archived the top 10 HN stories daily since 2010-07-20.
We scrape the HTML pages to get story titles, URLs, and HN item IDs,
then optionally enrich with score/comment data from the HN API.

Usage:
    uv run python -m hn_daily_index.backfill [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--commit-every N]

The --commit-every flag controls how often to git-commit (default: 30 days).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from hn_daily_index.generate import (
    DATA_DIR,
    PROJECT_ROOT,
    README_FILE,
    _date_to_path,
    _generate_readme,
    _generate_sub_readmes,
    _scan_available,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DAEMONOLOGY_URL = "https://www.daemonology.net/hn-daily/{date}.html"
HN_API = "https://hacker-news.firebaseio.com/v0"
HN_DAILY_START = date(2010, 7, 20)
REQUEST_DELAY = 0.5  # seconds between requests
API_DELAY = 0.2  # seconds between HN API requests

# ---------------------------------------------------------------------------
# Parse daemonology.net HTML
# ---------------------------------------------------------------------------

STORY_RE = re.compile(
    r'<span class="storylink"><a href="(?P<url>[^"]*)">'
    r"(?P<title>.*?)</a></span>.*?"
    r'<span class="postlink"><a href="https://news\.ycombinator\.com/item\?id=(?P<id>\d+)"',
    re.DOTALL,
)


def _parse_daily_html(html: str) -> list[dict]:
    """Extract stories from a daemonology.net daily page."""
    stories = []
    for i, m in enumerate(STORY_RE.finditer(html), 1):
        stories.append({
            "rank": i,
            "id": int(m.group("id")),
            "title": _unescape_html(m.group("title")),
            "url": m.group("url"),
            "score": 0,
            "by": "",
            "descendants": 0,
            "time": 0,
        })
    return stories


def _unescape_html(text: str) -> str:
    """Basic HTML entity unescaping."""
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&#x27;", "'")
    text = text.replace("&apos;", "'")
    return text


# ---------------------------------------------------------------------------
# Enrich with HN API (score, author, comments)
# ---------------------------------------------------------------------------


def _enrich_stories(client: httpx.Client, stories: list[dict]) -> None:
    """Fetch score/author/comments from HN API for each story."""
    for story in stories:
        try:
            resp = client.get(
                f"{HN_API}/item/{story['id']}.json", timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    story["score"] = data.get("score", 0) or 0
                    story["by"] = data.get("by", "")
                    story["descendants"] = data.get("descendants", 0) or 0
                    story["time"] = data.get("time", 0) or 0
            time.sleep(API_DELAY)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_day(d: date, stories: list[dict]) -> None:
    path = _date_to_path(d)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stories, indent=2) + "\n")


def _git_commit(message: str) -> None:
    try:
        subprocess.run(
            ["git", "add", "data/", "README.md"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=True,
        )
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=PROJECT_ROOT,
                capture_output=True,
                check=True,
            )
            print(f"  Committed: {message}", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill HN daily top stories from daemonology.net"
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=HN_DAILY_START,
        help=f"Start date (default: {HN_DAILY_START})",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=1),
        help="End date (default: yesterday)",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=30,
        help="Commit progress every N days fetched (default: 30)",
    )
    parser.add_argument(
        "--no-commit",
        action="store_true",
        help="Skip automatic git commits",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip HN API enrichment (faster, but no scores/authors)",
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    existing = set(_scan_available())

    # Build list of days to fetch
    days_to_fetch = []
    d = args.start
    while d <= args.end:
        if d.isoformat() not in existing:
            days_to_fetch.append(d)
        d += timedelta(days=1)

    total = len(days_to_fetch)
    if total == 0:
        print("Nothing to backfill, all days already have data.", file=sys.stderr)
        return

    print(
        f"Backfilling {total} days ({args.start} to {args.end}), "
        f"skipping {len(existing)} existing...",
        file=sys.stderr,
    )

    fetched = 0
    batch_start: date | None = None

    with httpx.Client() as client:
        for d in days_to_fetch:
            if batch_start is None:
                batch_start = d

            # Fetch from daemonology.net (with retry)
            url = DAEMONOLOGY_URL.format(date=d.isoformat())
            for attempt in range(3):
                try:
                    resp = client.get(url, timeout=15)
                    if resp.status_code == 200:
                        stories = _parse_daily_html(resp.text)
                        if stories:
                            if not args.no_enrich:
                                _enrich_stories(client, stories)
                            _save_day(d, stories)
                        break
                    elif resp.status_code == 404:
                        break  # No data for this day
                    else:
                        print(
                            f"  {d}: HTTP {resp.status_code}", file=sys.stderr
                        )
                except Exception as e:
                    if attempt < 2:
                        time.sleep(2)
                        continue
                    print(f"  {d}: {e}", file=sys.stderr)

            fetched += 1
            if fetched % 10 == 0 or fetched == total:
                pct = fetched * 100 // total
                print(
                    f"  [{fetched}/{total}] {pct}% - {d.isoformat()}",
                    file=sys.stderr,
                )

            # Periodic commit
            if not args.no_commit and fetched % args.commit_every == 0:
                readme = _generate_readme()
                README_FILE.write_text(readme)
                available_data = _scan_available()
                _generate_sub_readmes(available_data)
                _git_commit(
                    f"Backfill {batch_start.isoformat()} to {d.isoformat()}"
                )
                batch_start = None

            time.sleep(REQUEST_DELAY)

    # Final regeneration and commit
    print("Regenerating READMEs...", file=sys.stderr)
    readme = _generate_readme()
    README_FILE.write_text(readme)
    available_data = _scan_available()
    _generate_sub_readmes(available_data)

    if not args.no_commit and batch_start is not None:
        _git_commit(
            f"Backfill {batch_start.isoformat()} to {args.end.isoformat()}"
        )

    print(f"Done! Backfilled {fetched} days.", file=sys.stderr)


if __name__ == "__main__":
    main()
