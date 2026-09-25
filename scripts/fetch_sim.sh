#!/usr/bin/env bash
# Snapshot used for the committed sample: data/sim/raw/issues_2026-09-25.json
# Re-fetching today will differ (issues get edited, closed, deleted); the sample
# is reproducible only from the committed snapshot.
set -euo pipefail
gh issue list -R simstudioai/sim --state all --limit 2000 \
  --json number,title,body,labels,createdAt,author,url,state > "data/sim/raw/issues_$(date +%F).json"
