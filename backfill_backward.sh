#!/usr/bin/env bash
# Backfill HN daily data backward, one month at a time, committing each month.
# Usage: ./backfill_backward.sh [--no-enrich]
set -euo pipefail
cd "$(dirname "$0")"

NO_ENRICH="${1:-}"

# Generate month ranges from 2026-03 backward to 2010-07
year=2026
month=3

while true; do
    start=$(printf "%04d-%02d-01" "$year" "$month")

    # End date: last day of the month
    if [ "$month" -eq 12 ]; then
        next_year=$((year + 1))
        next_month=1
    else
        next_year=$year
        next_month=$((month + 1))
    fi
    end=$(date -j -f "%Y-%m-%d" "$(printf "%04d-%02d-01" "$next_year" "$next_month")" -v-1d "+%Y-%m-%d" 2>/dev/null || \
          python3 -c "from datetime import date; d=date($next_year,$next_month,1); from datetime import timedelta; print((d-timedelta(days=1)).isoformat())")

    month_label=$(printf "%04d-%02d" "$year" "$month")
    echo "=== Backfilling $month_label ($start to $end) ==="

    if [ "$NO_ENRICH" = "--no-enrich" ]; then
        uv run python -m hn_daily_index.backfill --start "$start" --end "$end" --no-commit --no-enrich 2>&1 || true
    else
        uv run python -m hn_daily_index.backfill --start "$start" --end "$end" --no-commit 2>&1 || true
    fi

    # Regenerate READMEs and commit
    uv run hn-daily-index 2>&1 || true

    git add data/ README.md
    if ! git diff --staged --quiet 2>/dev/null; then
        git commit -m "Backfill $month_label"
        git push
        echo "=== Committed and pushed $month_label ==="
    else
        echo "=== No new data for $month_label ==="
    fi

    # Move to previous month
    if [ "$year" -eq 2010 ] && [ "$month" -le 7 ]; then
        break
    fi

    month=$((month - 1))
    if [ "$month" -eq 0 ]; then
        month=12
        year=$((year - 1))
    fi
done

echo "=== Backfill complete ==="
