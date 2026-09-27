#!/usr/bin/env bash
# Commit the raw upstream availability copy back to the working branch.
#
# It is the baseline the next run compares against and the fallback when the
# upstream feed breaks, so it has to survive between runs. Nothing is pushed
# when the file has not changed, which is the usual case on a quiet day.
#
# If the branch moved while this run was building (another run, or a PR merge
# that carried its own copy), this run's copy is written on top of the new
# branch tip, unless the branch already holds a newer fetch.
set -euo pipefail

FILE="data/injuries-raw-latest.json"
BRANCH="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"

if [ ! -f "$FILE" ]; then
  echo "commit-raw: $FILE was not written this run, nothing to commit"
  exit 0
fi

git config user.name "${GIT_AUTHOR_NAME:-github-actions[bot]}"
git config user.email "${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}"

# Stage first, then compare against the index. `git diff` on the working tree
# ignores untracked files, so on the very first run it reported the file as
# unchanged and the copy was never committed at all.
# Keep this run's freshly fetched copy aside. On a rejected push it is
# written on top of whatever the branch now holds: the file is a snapshot
# where the newest fetch wins, so its contents are never merged.
OURS=$(mktemp)
cp "$FILE" "$OURS"
trap 'rm -f "$OURS" "${THEIRS:-}" "${TMP_INDEX:-}"' EXIT

# Stage first, then compare against the index. `git diff` on the working tree
# ignores untracked files, so on the very first run it reported the file as
# unchanged and the copy was never committed at all.
git add "$FILE"
if git diff --cached --quiet -- "$FILE"; then
  echo "commit-raw: $FILE is unchanged"
  exit 0
fi

ROWS=$(python -c "import json,sys;print(json.load(open('$FILE'))['row_count'])")
MESSAGE="Save raw availability feed ($ROWS rows)"
git commit -q -m "$MESSAGE"
COMMIT=HEAD

# Exit 0 when the copy in $2 is newer than the one in $1: the feed's own as-of
# (newest row date) first, then when it was fetched, since row dates only go
# down to the day. Rows dated more than a day after the copy was fetched are
# invalid and do not count toward its as-of, the same rule the build applies.
newer_than() {
  python - "$1" "$2" <<'PY'
import json, sys
from datetime import datetime, timedelta

def key(path):
    data = json.load(open(path))
    try:
        stamp = datetime.fromisoformat(data.get("fetched_at", ""))
        fetched, until = stamp.timestamp(), (stamp.date() + timedelta(days=1)).isoformat()
    except ValueError:
        fetched, until = 0.0, ""
    dates = ((r.get("date") or "")[:10] for r in data.get("rows") or [])
    as_of = max((d for d in dates if not until or d <= until), default="")
    return (as_of, fetched)

sys.exit(0 if key(sys.argv[2]) > key(sys.argv[1]) else 1)
PY
}

for attempt in 1 2 3; do
  if git push -q origin "$COMMIT:refs/heads/$BRANCH"; then
    echo "commit-raw: pushed $ROWS rows to $BRANCH"
    exit 0
  fi
  echo "commit-raw: push rejected, reapplying on top of origin/$BRANCH (attempt $attempt)"
  git fetch -q origin "$BRANCH"
  BASE=$(git rev-parse "origin/$BRANCH")

  if git cat-file -e "$BASE:$FILE" 2>/dev/null; then
    THEIRS=$(mktemp)
    git show "$BASE:$FILE" > "$THEIRS"
    if cmp -s "$OURS" "$THEIRS"; then
      echo "commit-raw: origin/$BRANCH already has this copy"
      exit 0
    fi
    if newer_than "$OURS" "$THEIRS"; then
      echo "commit-raw: origin/$BRANCH has a newer copy, leaving it"
      exit 0
    fi
  fi

  # One commit on top of the branch as it is now, changing only this file.
  # A throwaway index keeps the working tree and HEAD untouched.
  TMP_INDEX=$(mktemp)
  BLOB=$(git hash-object -w "$OURS")
  GIT_INDEX_FILE="$TMP_INDEX" git read-tree "$BASE"
  GIT_INDEX_FILE="$TMP_INDEX" git update-index --add --cacheinfo "100644,$BLOB,$FILE"
  TREE=$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)
  COMMIT=$(git commit-tree "$TREE" -p "$BASE" -m "$MESSAGE")
done

echo "commit-raw: could not push $FILE" >&2
exit 1
