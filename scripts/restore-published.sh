#!/usr/bin/env bash
# Pull the last published tree into ./site so a run can fall back to the last
# good data and so a refresh can update only the pages it needs.
set -euo pipefail

SITE_DIR="${1:-site}"
BRANCH="${2:-gh-pages}"

mkdir -p "$SITE_DIR"
if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
  git fetch -q --depth 1 origin "$BRANCH"
  git --work-tree="$SITE_DIR" checkout -q "origin/$BRANCH" -- .
  git reset -q
  echo "restore: pulled the last publish from $BRANCH"
else
  echo "restore: no $BRANCH yet, starting from empty"
fi
