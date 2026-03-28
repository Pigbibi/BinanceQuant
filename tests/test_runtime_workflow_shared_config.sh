#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
workflow_file="$repo_dir/.github/workflows/main.yml"

grep -Fq 'TG_TOKEN: ${{ secrets.TG_TOKEN }}' "$workflow_file"
grep -Fq 'GLOBAL_TELEGRAM_CHAT_ID: ${{ vars.GLOBAL_TELEGRAM_CHAT_ID }}' "$workflow_file"
grep -Fq 'NOTIFY_LANG: ${{ vars.NOTIFY_LANG }}' "$workflow_file"
grep -Fq 'GCP_SA_KEY: ${{ secrets.GCP_SA_KEY }}' "$workflow_file"
if grep -Fq 'TG_CHAT_ID:' "$workflow_file"; then
  echo "workflow should not pass TG_CHAT_ID anymore" >&2
  exit 1
fi
