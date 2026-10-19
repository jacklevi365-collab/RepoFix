.PHONY: setup setup-ui test lint demo serve

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install -r requirements/dev.lock
	.venv/bin/python -m pip install -e .

setup-ui:
	npm ci --ignore-scripts

test:
	PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v

lint:
	.venv/bin/ruff check src tests scripts
	.venv/bin/ruff format --check src tests scripts
	npm run lint
	npm test

demo:
	PYTHONPATH=src .venv/bin/python -m repofix run --repo examples/tinybug/repo --issue examples/tinybug/issue.md --verification examples/tinybug/verification --demo

serve:
	PYTHONPATH=src .venv/bin/python -m repofix serve
