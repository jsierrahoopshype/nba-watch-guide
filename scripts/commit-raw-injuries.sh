#!/usr/bin/env bash
# Commit the raw upstream availability copy back to the working branch.
#
# It is the baseline the next run compares against and the fallback when the
# upstream feed breaks, so it has to survive between runs. Nothing is pushed
# when the file has not changed, which is the usual case on a quiet day.
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
git add "$FILE"
if git diff --cached --quiet -- "$FILE"; then
  echo "commit-raw: $FILE is unchanged"
  exit 0
fi

ROWS=$(python -c "import json,sys;print(json.load(open('$FILE'))['row_count'])")
git commit -q -m "Save raw availability feed ($ROWS rows)"

# Another run may have pushed in between. Rebase onto it and try again rather
# than forcing, so a concurrent save is never thrown away.
for attempt in 1 2 3; do
  if git push -q origin "HEAD:$BRANCH"; then
    echo "commit-raw: pushed $ROWS rows to $BRANCH"
    exit 0
  fi
  echo "commit-raw: push rejected, rebasing (attempt $attempt)"
  git fetch -q origin "$BRANCH"
  git rebase -q "origin/$BRANCH" || { git rebase --abort || true; break; }
done

echo "commit-raw: could not push $FILE" >&2
exit 1
