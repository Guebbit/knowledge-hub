# Developer entry points for knowledge-hub.
#
# Everything here runs on the host in a throwaway .venv — the tests cover pure
# logic (module grouping, scope filtering, graph parsing) and need neither the
# container, nor Ollama, nor an API key. The container image is for running the
# pipeline (2brain / 2repo), not for developing it.

VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
RUFF    := $(VENV)/bin/ruff

.DEFAULT_GOAL := help
.PHONY: help venv test lint fix check image clean

help:  ## Show this help
	@awk -F':.*?## ' '/^[a-z-]+:.*?## /{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# The project is a script collection, not an installable package (flat layout,
# with vault/ and graphify/ at the root), so nothing is pip-installed from it.
# pytest picks the imports up via `pythonpath = ["scripts"]` in pyproject.toml.
$(VENV)/bin/activate: pyproject.toml
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet pytest ruff pathspec python-dotenv
	@touch $(VENV)/bin/activate

venv: $(VENV)/bin/activate  ## Create the dev virtualenv

test: venv  ## Run the test suite
	$(PY) -m pytest -q

lint: venv  ## Lint without changing anything
	$(RUFF) check scripts tests

fix: venv  ## Apply ruff's safe fixes
	$(RUFF) check --fix scripts tests

check: lint test  ## Everything CI runs

image:  ## Rebuild the scripts container image
	podman-compose build scripts

clean:  ## Remove the dev virtualenv and caches
	rm -rf $(VENV) .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
