"""
Enrich existing JSON data files that are missing scores/authors.

Reads all data/YYYY/MM/DD.json files, finds stories with score=0,
and fetches metadata from the HN API using parallel async requests.

Usage:
    uv run python -m hn_daily_index.enrich [--commit-every N] [--concurrency N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx

from hn_daily_index.generate import (
    DATA_DIR,
    PROJECT_ROOT,
    README_FILE,
    _generate_readme,
    _generate_sub_readmes,
    _scan_available,
)

HN_API = "https://hacker-news.firebaseio.com/v0"
DEFAULT_CONCURRENCY = 10


def _needs_enrichment(stories: list[dict]) -> bool:
    return any(s.get("score", 0) == 0 and s.get("id") for s in stories)


async def _fetch_item(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    story_id: int,
) -> dict | None:
    """Fetch a single item from HN API with semaphore rate limiting."""
    async with sem:
        for attempt in range(3):
            try:
                resp = await client.get(
                    f"{HN_API}/item/{story_id}.json", timeout=10
                )
                if resp.status_code == 200:
                    return resp.json()
                break
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(1)
    return None


async def _enrich_file(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    path: Path,
) -> bool:
    """Enrich a single JSON file with parallel API calls. Returns True if updated."""
    stories = json.loads(path.read_text())
    if not _needs_enrichment(stories):
        return False

    # Gather all stories that need enrichment
    to_enrich = [s for s in stories if s.get("score", 0) == 0 and s.get("id")]
    if not to_enrich:
        return False

    # Fetch all in parallel (bounded by semaphore)
    tasks = [_fetch_item(client, sem, s["id"]) for s in to_enrich]
    results = await asyncio.gather(*tasks)

    updated = False
    for story, data in zip(to_enrich, results):
        if data:
            story["score"] = data.get("score", 0) or 0
            story["by"] = data.get("by", "")
            story["descendants"] = data.get("descendants", 0) or 0
            story["time"] = data.get("time", 0) or 0
            updated = True

    if updated:
        path.write_text(json.dumps(stories, indent=2) + "\n")
    return updated


def _git_commit(message: str) -> None:
    try:
        subprocess.run(
            ["git", "add", "data/", "README.md"],
            cwd=PROJECT_ROOT, capture_output=True, check=True,
        )
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=PROJECT_ROOT, capture_output=True,
        )
        if result.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=PROJECT_ROOT, capture_output=True, check=True,
            )
            print(f"  Committed: {message}", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"  Git error: {e}", file=sys.stderr)


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Enrich data files with HN API metadata")
    parser.add_argument(
        "--commit-every", type=int, default=30,
        help="Commit every N enriched files (default: 30)",
    )
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument(
        "--concurrency", type=int, default=DEFAULT_CONCURRENCY,
        help=f"Max concurrent API requests (default: {DEFAULT_CONCURRENCY})",
    )
    args = parser.parse_args()

    # Find all JSON files that need enrichment
    files_to_enrich = []
    for json_file in sorted(DATA_DIR.glob("*/*/*.json"), reverse=True):
        stories = json.loads(json_file.read_text())
        if _needs_enrichment(stories):
            files_to_enrich.append(json_file)

    total = len(files_to_enrich)
    if total == 0:
        print("All files already enriched.", file=sys.stderr)
        return

    print(f"Enriching {total} files (concurrency={args.concurrency})...", file=sys.stderr)

    enriched = 0
    batch_start: str | None = None
    sem = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient() as client:
        for path in files_to_enrich:
            label = f"{path.parent.parent.name}/{path.parent.name}/{path.stem}"
            if batch_start is None:
                batch_start = label

            if await _enrich_file(client, sem, path):
                enriched += 1

            if enriched % 10 == 0 or enriched == total:
                print(f"  [{enriched}/{total}] {label}", file=sys.stderr)

            if (
                not args.no_commit
                and enriched > 0
                and enriched % args.commit_every == 0
            ):
                readme = _generate_readme()
                README_FILE.write_text(readme)
                available_data = _scan_available()
                _generate_sub_readmes(available_data)
                _git_commit(f"Enrich {batch_start} to {label}")
                batch_start = None

    # Final commit
    if enriched > 0:
        print("Regenerating READMEs...", file=sys.stderr)
        readme = _generate_readme()
        README_FILE.write_text(readme)
        available_data = _scan_available()
        _generate_sub_readmes(available_data)
        if not args.no_commit and batch_start is not None:
            _git_commit(f"Enrich {batch_start} to {label}")

    print(f"Done! Enriched {enriched} files.", file=sys.stderr)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
