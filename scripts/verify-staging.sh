#!/usr/bin/env bash
set -euo pipefail

base_url="${1:?Usage: bash scripts/verify-staging.sh https://your-app.example}"
base_url="${base_url%/}"

printf 'Checking liveness: %s/health/live\n' "$base_url"
curl --fail --silent --show-error "$base_url/health/live"
printf '\n'

printf 'Checking readiness: %s/health/ready\n' "$base_url"
curl --fail --silent --show-error "$base_url/health/ready"
printf '\n'

printf 'Staging health checks passed.\n'
