# hn-daily-index

A daily archive of the top 10 stories on [Hacker News](https://news.ycombinator.com), organized by date.

## How it works

Every day a GitHub Action runs and does the following:

1. **Fetch** the current top 10 story IDs from the HN API (`/v0/topstories.json`), then fetch each story's details (title, URL, score, author, comment count).

2. **Save** the raw data as a JSON file under `data/YYYY-MM-DD.json`. This is the source of truth. One file per day, never overwritten.

3. **Rebuild** the full `README.md` from all JSON files in `data/`. The README is not edited incrementally. It is regenerated from scratch each time, so the table of contents and monthly groupings stay consistent.

The README shows each day as its own section with a numbered list of stories. The table of contents groups days by month for easy navigation.

## Setup

```sh
uv sync
```

## Usage

```sh
uv run hn-daily-index
```

This fetches today's top 10 and regenerates `README.md`.

## Data format

Each `data/YYYY-MM-DD.json` file contains an array of 10 story objects:

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
│   ├── README.md                # this file
│   └── hn_daily_index/
│       ├── __init__.py
│       └── generate.py          # fetch, save, render
├── .github/
│   └── workflows/
│       └── update.yml           # daily scheduled run
├── data/
│   ├── 2026-04-02.json          # one file per day
│   └── ...
├── README.md                    # generated output (do not edit by hand)
└── LICENSE
```
