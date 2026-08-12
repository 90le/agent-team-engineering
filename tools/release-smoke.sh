#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp_root="$(mktemp -d)"
cleanup() {
  rm -rf -- "$temp_root"
}
trap cleanup EXIT

git clone --quiet "file://$repo_root" "$temp_root/source"
cd "$temp_root/source"

version="$(tr -d '\r\n' < VERSION)"
release_tag="v$version"
head_revision="$(git rev-parse HEAD)"
if git show-ref --verify --quiet "refs/tags/$release_tag"; then
  test "$(git cat-file -t "refs/tags/$release_tag")" = "tag"
  test "$(git rev-parse "$release_tag^{}")" = "$head_revision"
else
  git -c user.name="Agent Team Factory CI" \
    -c user.email="factory-ci@invalid.example" \
    tag -a "$release_tag" -m "Simulated release $release_tag" HEAD
fi

tools/verify.sh
python3 tools/agent_team.py doctor >/dev/null
python3 tools/agent_team.py factory install --output "$temp_root/installed" >/dev/null
python3 "$temp_root/installed/tools/agent_team.py" factory verify \
  --root "$temp_root/installed" >/dev/null
python3 "$temp_root/installed/tools/agent_team.py" doctor >/dev/null
"$temp_root/installed/agent-team" create \
  --design "$temp_root/installed/examples/context-first/team-design.json" \
  --output "$temp_root/context-team" >/dev/null
"$temp_root/installed/agent-team" context validate \
  --root "$temp_root/context-team" >/dev/null
"$temp_root/installed/agent-team" onboard plan \
  --project-path "$temp_root/source" \
  --purpose research-knowledge \
  --automation assisted \
  --goal "Create a source-checked release knowledge team" \
  --platform openclaw \
  --team-name "Release Knowledge Team" \
  --project-name "Release Knowledge" \
  --owner "Release Owner" \
  --provider generic-git \
  --repository local/release-knowledge \
  --output "$temp_root/guided-team" \
  --plan "$temp_root/guided-plan.json" >/dev/null
guided_digest="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["proposal_digest"])' "$temp_root/guided-plan.json")"
"$temp_root/installed/agent-team" onboard confirm \
  --plan "$temp_root/guided-plan.json" \
  --digest "$guided_digest" \
  --approved-by "Release Owner" >/dev/null
"$temp_root/installed/agent-team" onboard apply \
  --plan "$temp_root/guided-plan.json" >/dev/null
"$temp_root/installed/agent-team" context validate \
  --root "$temp_root/guided-team" >/dev/null
test -f "$temp_root/guided-team/GETTING-STARTED.md"
"$temp_root/installed/agent-team" host list >/dev/null
"$temp_root/installed/agent-team" host plan \
  --team "$temp_root/guided-team" \
  --target openclaw \
  --destination "$temp_root/openclaw-projection" \
  --output "$temp_root/openclaw-host-plan.json" >/dev/null
"$temp_root/installed/agent-team" host preview \
  --plan "$temp_root/openclaw-host-plan.json" >/dev/null
host_digest="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["proposal_digest"])' "$temp_root/openclaw-host-plan.json")"
"$temp_root/installed/agent-team" host confirm \
  --plan "$temp_root/openclaw-host-plan.json" \
  --digest "$host_digest" \
  --approved-by "Release Owner" >/dev/null
"$temp_root/installed/agent-team" host apply \
  --plan "$temp_root/openclaw-host-plan.json" >/dev/null
"$temp_root/installed/agent-team" host verify \
  --root "$temp_root/openclaw-projection" >/dev/null
"$temp_root/installed/agent-team" host uninstall-preview \
  --root "$temp_root/openclaw-projection" >/dev/null
"$temp_root/installed/agent-team" host uninstall \
  --root "$temp_root/openclaw-projection" \
  --digest "$host_digest" >/dev/null
"$temp_root/installed/agent-team" host uninstall-preview \
  --root "$temp_root/openclaw-projection" >/dev/null
"$temp_root/installed/agent-team" host uninstall \
  --root "$temp_root/openclaw-projection" \
  --digest "$host_digest" >/dev/null
python3 "$temp_root/installed/tools/agent_team.py" instance init \
  --config "$temp_root/installed/examples/team-instance/input/instance.json" \
  --output "$temp_root/instance" >/dev/null
python3 "$temp_root/installed/tools/agent_team.py" instance validate \
  --root "$temp_root/instance" >/dev/null

writer_report="$("$temp_root/installed/agent-team" native writer-authority-validate \
  --topology "$temp_root/installed/examples/v08-contracts/valid/writer-topology.json" \
  --plan "$temp_root/installed/examples/v08-contracts/valid/plan-revision.json" \
  --approval "$temp_root/installed/examples/v08-contracts/valid/approval-grant.json")"
python3 -c 'import json,sys; report=json.load(sys.stdin); assert report["status"] == "VALID"; assert report["automatic_execution"] is False; assert report["identity_or_signature_verified"] is False' <<<"$writer_report"

printf 'release_smoke=PASS tag=%s revision=%s\n' "$release_tag" "$head_revision"
