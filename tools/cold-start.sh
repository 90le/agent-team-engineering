#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temp_root="$(mktemp -d)"
cleanup() {
  rm -rf -- "$temp_root"
}
trap cleanup EXIT

git clone --quiet "file://$repo_root" "$temp_root/agent-team-engineering"
cd "$temp_root/agent-team-engineering"
python3 tools/agent_team.py validate
test "$(./agent-team --version)" = "$(tr -d '\r\n' < VERSION)"
./agent-team native contract-validate \
  --contract team_spec \
  --file examples/v08-contracts/valid/team-spec.json >/dev/null
./agent-team native demo --database "$temp_root/native.sqlite3" >/dev/null
./agent-team native verify --database "$temp_root/native.sqlite3" >/dev/null
./agent-team presets >/dev/null
./agent-team create \
  --design examples/context-first/team-design.json \
  --output "$temp_root/context-team-a" >/dev/null
./agent-team create \
  --design examples/context-first/team-design.json \
  --output "$temp_root/context-team-b" >/dev/null
./agent-team context validate --root "$temp_root/context-team-a" >/dev/null
diff -ru "$temp_root/context-team-a" "$temp_root/context-team-b"
./agent-team onboard plan \
  --project-path . \
  --purpose software \
  --automation assisted \
  --goal "Create a portable team for reviewed changes" \
  --platform generic-ai \
  --team-name "Cold Start Guided Team" \
  --project-name "Cold Start Project" \
  --owner "Cold Start Owner" \
  --provider generic-git \
  --repository local/cold-start \
  --output "$temp_root/guided-team" \
  --plan "$temp_root/guided-plan.json" >/dev/null
./agent-team onboard preview --plan "$temp_root/guided-plan.json" >/dev/null
guided_digest="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["proposal_digest"])' "$temp_root/guided-plan.json")"
./agent-team onboard confirm \
  --plan "$temp_root/guided-plan.json" \
  --digest "$guided_digest" \
  --approved-by "Cold Start Owner" >/dev/null
./agent-team onboard apply --plan "$temp_root/guided-plan.json" >/dev/null
./agent-team context validate --root "$temp_root/guided-team" >/dev/null
test -f "$temp_root/guided-team/GETTING-STARTED.md"
test -z "$(git status --porcelain --untracked-files=all)"
python3 -m unittest discover -s tests -v
python3 tools/agent_team.py simulate --approve-production >/dev/null
python3 tools/cross_ai_takeover.py >/dev/null
python3 tools/agent_team.py instance init \
  --config examples/team-instance/input/instance.json \
  --output "$temp_root/instance-a" >/dev/null
python3 tools/agent_team.py instance init \
  --config examples/team-instance/input/instance.json \
  --output "$temp_root/instance-b" >/dev/null
python3 tools/agent_team.py instance validate --root "$temp_root/instance-a"
diff -ru "$temp_root/instance-a" "$temp_root/instance-b"
git fsck --full
