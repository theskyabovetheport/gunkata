#!/usr/bin/env bash
# Every gate this repo has: lint, docs build, then the whole test suite.
# The CLAUDE.md Definition of Done runs this; when there is no CI, this
# script is the whole of it.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "--- ruff check ---"
uv run ruff check .

echo "--- mkdocs build --strict ---"
uv run mkdocs build --strict

echo "--- pytest ---"
uv run pytest -m "not emulator" "$@"
