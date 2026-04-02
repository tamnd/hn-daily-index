#!/usr/bin/env bash
# Backfill HN daily data backward, one month at a time, committing each month.
# Usage: ./backfill_backward.sh [--no-enrich]
set -euo pipefail
cd "$(dirname "$0")"

NO_ENRICH="${1:-}"
ENRICH_FLAG=""
if [ "$NO_ENRICH" = "--no-enrich" ]; then
    ENRICH_FLAG="--no-enrich"
fi

# Generate month ranges from 2026-03 backward to 2010-07 using Python
MONTHS=$(python3 -c "
from datetime import date
import calendar
y, m = 2026, 3
while (y, m) >= (2010, 7):
    last_day = calendar.monthrange(y, m)[1]
    end = date(y, m, last_day)
    yesterday = date.today().replace(day=1).__class__.today()
    if end > yesterday:
        end = yesterday
    print(f'{y:04d}-{m:02d}-01,{end.isoformat()},{y:04d}-{m:02d}')
    m -= 1
    if m == 0:
        m = 12
        y -= 1
")

echo "$MONTHS" | while IFS=',' read -r start end label; do
    echo "=== Backfilling $label ($start to $end) ==="

    uv run python -m hn_daily_index.backfill \
        --start "$start" --end "$end" \
        --no-commit $ENRICH_FLAG 2>&1 || true

    # Regenerate READMEs
    uv run hn-daily-index 2>&1 || true

    git add data/ README.md
    if ! git diff --staged --quiet 2>/dev/null; then
        git commit -m "Backfill $label"
        git push
        echo "=== Committed and pushed $label ==="
    else
        echo "=== No new data for $label ==="
    fi
done

echo "=== Backfill complete ==="
