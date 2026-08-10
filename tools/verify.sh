#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python3 tools/agent_team.py validate
python3 -m unittest discover -s tests -v
python3 tools/agent_team.py simulate >/dev/null
python3 tools/agent_team.py simulate --approve-production >/dev/null
python3 tools/cross_ai_takeover.py >/dev/null

temp_root="$(mktemp -d)"
cleanup() {
  rm -rf -- "$temp_root"
}
trap cleanup EXIT
python3 tools/agent_team.py instance init \
  --config examples/team-instance/input/instance.json \
  --output "$temp_root/instance" >/dev/null
python3 tools/agent_team.py instance validate --root "$temp_root/instance"
