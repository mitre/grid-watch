#!/bin/bash
# Run all formatting and linting checks.
# Exit immediately if any check fails.
set -e
echo "Running black..."
black --check --exclude '/(\.venv|venv|\.ci_venv_.*)/' .
echo "Running ruff..."
ruff check --exclude .venv --exclude '.ci_venv_*' .
echo "Running mypy..."
mypy dnp3-sim
echo "All checks passed."
