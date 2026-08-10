.PHONY: doctor validate test simulate cold-test

doctor:
	python3 tools/agent_team.py doctor

validate:
	python3 tools/agent_team.py validate

test:
	python3 -m unittest discover -s tests -v

simulate:
	python3 tools/agent_team.py simulate --approve-production

cold-test:
	tools/cold-start.sh
