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
./agent-team presets >/dev/null
./agent-team create \
  --design examples/context-first/team-design.json \
  --output "$temp_root/context-team-a" >/dev/null
./agent-team create \
  --design examples/context-first/team-design.json \
  --output "$temp_root/context-team-b" >/dev/null
./agent-team context validate --root "$temp_root/context-team-a" >/dev/null
diff -ru "$temp_root/context-team-a" "$temp_root/context-team-b"
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
