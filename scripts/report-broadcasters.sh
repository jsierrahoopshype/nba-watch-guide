#!/usr/bin/env bash
# Print how much of the season has a broadcaster, and put it in the run summary.
#
# The league fills national assignments in over time, so this is the line to
# watch: when games_with_national_tv jumps, the schedule has been updated.
set -euo pipefail

SITE_DIR="${1:-site}"
REPORT="$SITE_DIR/data/broadcast-coverage.json"

if [ ! -f "$REPORT" ]; then
  echo "broadcasters: $REPORT is missing" >&2
  exit 1
fi

python - "$REPORT" <<'PY'
import json, os, sys
report = json.load(open(sys.argv[1]))
total = report["regular_season_games"] or 1
natl = report["games_with_national_tv"]
lines = [
    f"Season {report['season']}, {report['regular_season_games']} regular-season games",
    f"National TV: {natl} ({100.0 * natl / total:.1f}%)",
    f"Local TV: {report['games_with_local_tv']}",
    f"No broadcaster yet: {report['games_with_no_broadcaster']}",
    "National codes: " + (", ".join(f"{k} {v}" for k, v in report["national_codes"].items()) or "none"),
]
for line in lines:
    print(line)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as fh:
        fh.write("### Broadcaster coverage\n\n")
        for line in lines:
            fh.write(f"- {line}\n")
PY
