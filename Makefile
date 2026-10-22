# Tasks for the voice agent service.  Run "make" to see them all.

PYTHON := .venv/bin/python
PIP    := .venv/bin/pip

.DEFAULT_GOAL := help
.PHONY: help install install-dev test lint seed run reset clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Install the dependencies
	$(PIP) install -r requirements.txt

install-dev:  ## Install the dependencies and the development tools
	$(PIP) install -r requirements-dev.txt

test:  ## Run the test suite
	DJANGO_SETTINGS_MODULE=voice_service.settings MINIDB_PATH=:memory: \
		$(PYTHON) manage.py test agents

lint:  ## Check the code for problems
	$(PYTHON) -m pyflakes agents voice_service

seed:  ## Fill the database with example models and agents
	$(PYTHON) manage.py seed

run:  ## Start the server on http://127.0.0.1:8000
	$(PYTHON) manage.py runserver

reset:  ## Empty the database and start again
	rm -f voice.db voice.db-wal voice.db-shm
	$(MAKE) seed

clean:  ## Remove the caches and the local databases
	rm -f voice.db voice.db-wal voice.db-shm django.sqlite3
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
