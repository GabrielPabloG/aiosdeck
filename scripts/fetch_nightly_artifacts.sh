#!/usr/bin/env bash
# Fetch and analyze the latest (failed) Nightly mutation artifacts.
#
# Usage:
#   scripts/fetch_nightly_artifacts.sh [options]
#
# Options:
#   --run-id ID        Specific run id (default: latest failed nightly)
#   --branch BRANCH    Filter runs by branch (default: main)
#   --workflow FILE    Workflow file name (default: nightly.yml)
#   --out DIR          Output dir (default: .nightly-artifacts)
#   --with-report      Also download nightly-mutation-report (large)
#   --list             List recent nightly runs and exit
#   -h, --help         Show this help
#
# Requires an authenticated gh CLI (API over HTTPS; SSH is not used).
set -euo pipefail

WORKFLOW="nightly.yml"
BRANCH="main"
OUT=".nightly-artifacts"
RUN_ID=""
WITH_REPORT=0
LIST_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID="$2"; shift 2;;
    --branch) BRANCH="$2"; shift 2;;
    --workflow) WORKFLOW="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --with-report) WITH_REPORT=1; shift;;
    --list) LIST_ONLY=1; shift;;
    -h|--help) sed -n '2,16p' "$0"; exit 0;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done

command -v gh >/dev/null || { echo "gh not installed" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh not authenticated; run: gh auth login" >&2; exit 1; }

if [[ "$LIST_ONLY" == "1" ]]; then
  gh run list --workflow "$WORKFLOW" --branch "$BRANCH" --limit 15 \
    --json databaseId,conclusion,createdAt,headSha
  exit 0
fi

if [[ -z "$RUN_ID" ]]; then
  RUN_ID=$(gh run list --workflow "$WORKFLOW" --branch "$BRANCH" --status failure \
    --limit 1 --json databaseId --jq '.[0].databaseId')
  if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
    echo "no failed $WORKFLOW run found on $BRANCH" >&2
    exit 1
  fi
fi

mkdir -p "$OUT"
echo ">> run: $RUN_ID"
gh run view "$RUN_ID" --json headSha,headBranch,conclusion,createdAt,url \
  --jq '"   sha=\(.headSha) branch=\(.headBranch) conclusion=\(.conclusion) url=\(.url)"'
echo ">> local HEAD: $(git rev-parse HEAD)"

echo ">> downloading nightly-mutation-triage"
rm -rf "$OUT/triage"
gh run download "$RUN_ID" -n nightly-mutation-triage -D "$OUT/triage"

if [[ "$WITH_REPORT" == "1" ]]; then
  echo ">> downloading nightly-mutation-report (large)"
  rm -rf "$OUT/report"
  gh run download "$RUN_ID" -n nightly-mutation-report -D "$OUT/report"
fi

TRIAGE_JSON=$(find "$OUT/triage" -name mutation-triage.json | head -1 || true)
if [[ -z "$TRIAGE_JSON" ]]; then
  echo "triage JSON not found under $OUT/triage" >&2
  exit 1
fi
echo ">> triage: $TRIAGE_JSON"

python - "$TRIAGE_JSON" <<'PY'
import json
import sys
from collections import defaultdict

d = json.load(open(sys.argv[1]))
recs = d.get("records", [])
surv = [r for r in recs if r.get("status") == "survived" and not r.get("allowlisted")]
by_func = defaultdict(int)
by_cat = defaultdict(lambda: defaultdict(int))
for r in surv:
    by_func[r["func"]] += 1
    by_cat[r["func"]][r["category"]] += 1
print(f"killable survivors: {len(surv)}")
print(f"distinct funcs: {len(by_func)}")
print("top 25 functions:")
for i, (f, c) in enumerate(sorted(by_func.items(), key=lambda kv: -kv[1])[:25], 1):
    cats = ", ".join(f"{k}={v}" for k, v in sorted(by_cat[f].items(), key=lambda kv: -kv[1]))
    print(f"  {i:2d} {c:4d}  {f.split(chr(0x1c1))[-1]:45s} [{cats}]")
PY

cat <<EOF

Next:
  - Compare the run headSha with local HEAD above.
  - Analyze: $TRIAGE_JSON
  - (optional) regenerate evidence from report:
      python .pre-commit/mutation_evidence.py --mutants-dir $OUT/report --out $OUT/analysis --tests-dir tests
EOF
