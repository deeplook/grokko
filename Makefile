.PHONY: install lint format typecheck test coverage check build publish publish-test clean install-tool uninstall-tool

PLUGINS ?=

install:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src/grokko tests

test:
	uv run pytest

coverage:
	uv run coverage run -m pytest
	uv run coverage report

check: lint typecheck test

build:
	uv build

publish:
	uv publish --token $${PYPI_TOKEN}

publish-test:
	uv publish --index testpypi --token $${TEST_PYPI_TOKEN}

install-tool:
	uv tool install --reinstall $(foreach plugin,$(PLUGINS),--with $(plugin)) .

uninstall-tool:
	uv tool uninstall grokko

clean:
	rm -rf .venv dist *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name .DS_Store -exec rm {} +
