#!/usr/bin/env bash
# Publish the built site as one fresh commit on gh-pages.
#
# main keeps a clean history: the site is rebuilt several times a day, so
# gh-pages is force-pushed with a single orphan commit each time instead of
# collecting thousands of build commits.
#
# Never publishes a partial build: the index.html files in the tree must be
# exactly the paths in data/expected-pages.txt, which the build writes from
# data/teams.json and data/countries.json (see watchguide/manifest.py).
# PUBLISH_CHECK_ONLY=1 runs the checks and stops before touching git.
set -euo pipefail

SITE_DIR="${1:-site}"
BRANCH="${2:-gh-pages}"
MANIFEST="$SITE_DIR/data/expected-pages.txt"

if [ ! -f "$SITE_DIR/index.html" ]; then
  echo "publish: $SITE_DIR/index.html is missing, refusing to publish" >&2
  exit 1
fi
if [ ! -s "$MANIFEST" ]; then
  echo "publish: $MANIFEST is missing or empty, refusing to publish" >&2
  exit 1
fi

EXPECTED_LIST="$(mktemp)"
FOUND_LIST="$(mktemp)"
trap 'rm -f "$EXPECTED_LIST" "$FOUND_LIST"' EXIT
grep -v '^[[:space:]]*$' "$MANIFEST" | LC_ALL=C sort -u > "$EXPECTED_LIST"
(cd "$SITE_DIR" && find . -name index.html -type f | sed 's|^\./||') | LC_ALL=C sort > "$FOUND_LIST"

EXPECTED=$(wc -l < "$EXPECTED_LIST" | tr -d ' ')
PAGES=$(wc -l < "$FOUND_LIST" | tr -d ' ')
MISSING="$(LC_ALL=C comm -23 "$EXPECTED_LIST" "$FOUND_LIST")"
UNEXPECTED="$(LC_ALL=C comm -13 "$EXPECTED_LIST" "$FOUND_LIST")"

if [ "$PAGES" -ne "$EXPECTED" ] || [ -n "$MISSING" ] || [ -n "$UNEXPECTED" ]; then
  echo "publish: expected $EXPECTED pages, found $PAGES, refusing to publish" >&2
  if [ -n "$MISSING" ]; then
    echo "publish: missing pages:" >&2
    printf '%s\n' "$MISSING" | sed 's/^/  /' >&2
  fi
  if [ -n "$UNEXPECTED" ]; then
    echo "publish: unexpected pages:" >&2
    printf '%s\n' "$UNEXPECTED" | sed 's/^/  /' >&2
  fi
  exit 1
fi
echo "publish: $PAGES pages match $MANIFEST"

if [ "${PUBLISH_CHECK_ONLY:-}" = "1" ]; then
  exit 0
fi

# Hashed CSS/JS copies first seen more than 7 days ago that no page names are
# deleted before the push; the current ones never are (watchguide/prune.py).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" "${PYTHON:-python3}" -m watchguide --out "$SITE_DIR" \
  prune-assets --keep-days "${PUBLISH_KEEP_DAYS:-7}"

WORK="$(mktemp -d)"
cp -a "$SITE_DIR/." "$WORK/"
cd "$WORK"

git init -q
git checkout -q -b "$BRANCH"
git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"
git add -A
git commit -q -m "Publish watch guide $(date -u +'%Y-%m-%d %H:%M UTC')"
# PUBLISH_REMOTE lets a test push to a local repository instead.
REMOTE="${PUBLISH_REMOTE:-https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git}"
git push -q --force "$REMOTE" "$BRANCH"
echo "publish: pushed $PAGES pages to $BRANCH"
