.PHONY: doctor validate test simulate context-smoke instance-smoke cold-test

doctor:
	python3 tools/agent_team.py doctor

validate:
	python3 tools/agent_team.py validate

test:
	python3 -m unittest discover -s tests -v

simulate:
	python3 tools/agent_team.py simulate --approve-production

context-smoke:
	tmp="$$(mktemp -d)"; trap 'rm -rf -- "$$tmp"' EXIT; \
	./agent-team create --design examples/context-first/team-design.json --output "$$tmp/team"; \
	./agent-team context validate --root "$$tmp/team"

instance-smoke:
	tmp="$$(mktemp -d)"; trap 'rm -rf -- "$$tmp"' EXIT; \
	python3 tools/agent_team.py instance init --config examples/team-instance/input/instance.json --output "$$tmp/instance"; \
	python3 tools/agent_team.py instance validate --root "$$tmp/instance"

cold-test:
	tools/cold-start.sh
