# hn-daily-index

A daily archive of the top 10 stories on [Hacker News](https://news.ycombinator.com), organized by date.

## How it works

Every day a GitHub Action runs and does the following:

1. **Fetch** the current top 10 story IDs from the HN API (`/v0/topstories.json`), then fetch each story's details (title, URL, score, author, comment count).

2. **Save** the data as `data/YYYY/MM/DD.json`. One file per day, never overwritten. This is the source of truth.

3. **Rebuild** all READMEs from the JSON files:
   - `README.md` at the root with a full-year calendar and all stories.
   - `data/YYYY/README.md` for each year with links to monthly pages and all stories inline.
   - `data/YYYY/MM/README.md` for each month with a day-by-day listing.

The README is regenerated from scratch each time so the calendar and groupings stay consistent.

## Setup

```sh
uv sync
```

## Daily usage

```sh
uv run hn-daily-index
```

Fetches today's top 10 and regenerates all READMEs.

## Backfill

Historical data going back to 2010-07-20 can be backfilled from [daemonology.net/hn-daily](https://www.daemonology.net/hn-daily/), which archives the top 10 HN stories daily.

```sh
# Backfill everything (2010-07-20 to yesterday)
uv run python -m hn_daily_index.backfill

# Backfill a specific range
uv run python -m hn_daily_index.backfill --start 2024-01-01 --end 2024-12-31

# Faster: skip HN API enrichment (no scores/authors, just titles and links)
uv run python -m hn_daily_index.backfill --no-enrich

# Don't auto-commit (useful for testing)
uv run python -m hn_daily_index.backfill --no-commit
```

The backfill script:
- Scrapes story titles, URLs, and HN item IDs from daemonology.net HTML pages.
- Optionally enriches each story with score, author, and comment count from the HN API.
- Skips days that already have data, so it's safe to run multiple times.
- Auto-commits every 30 days of progress (configurable with `--commit-every N`), so you can resume if interrupted.

## Data format

Each `data/YYYY/MM/DD.json` file contains an array of story objects:

```json
[
  {
    "rank": 1,
    "id": 12345678,
    "title": "Story Title",
    "url": "https://example.com/article",
    "score": 342,
    "by": "username",
    "descendants": 128,
    "time": 1712000000
  }
]
```

## Project structure

```
hn-daily-index/
├── pyproject.toml
├── src/
│   ├── README.md                    # this file
│   └── hn_daily_index/
│       ├── __init__.py
│       ├── generate.py              # daily fetch, save, render
│       └── backfill.py              # historical backfill from daemonology.net
├── .github/
│   └── workflows/
│       └── update.yml               # daily scheduled run at 23:55 UTC
├── data/
│   └── YYYY/
│       ├── README.md                # yearly index with all stories
│       └── MM/
│           ├── README.md            # monthly index with all stories
│           └── DD.json              # raw story data for one day
├── README.md                        # generated root index (do not edit)
├── contributing.md
└── LICENSE
```
