#!/usr/bin/env bash
set -euo pipefail

# Run formatting and lint autofixes
echo "Running black..."
black .

echo "Running ruff..."
ruff check . --fix
ruff format .
