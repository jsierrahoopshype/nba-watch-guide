#!/usr/bin/env bash
# Publish the built site as one fresh commit on gh-pages.
#
# main keeps a clean history: the site is rebuilt several times a day, so
# gh-pages is force-pushed with a single orphan commit each time instead of
# collecting thousands of build commits.
set -euo pipefail

SITE_DIR="${1:-site}"
BRANCH="${2:-gh-pages}"

if [ ! -f "$SITE_DIR/index.html" ]; then
  echo "publish: $SITE_DIR/index.html is missing, refusing to publish" >&2
  exit 1
fi
PAGES=$(find "$SITE_DIR" -name index.html | wc -l)
if [ "$PAGES" -ne 32 ]; then
  echo "publish: expected 32 pages, found $PAGES, refusing to publish" >&2
  exit 1
fi

WORK="$(mktemp -d)"
cp -a "$SITE_DIR/." "$WORK/"
cd "$WORK"

git init -q
git checkout -q -b "$BRANCH"
git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
git add -A
git commit -q -m "Publish watch guide $(date -u +'%Y-%m-%d %H:%M UTC')"
git push -q --force "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "$BRANCH"
echo "publish: pushed $PAGES pages to $BRANCH"
