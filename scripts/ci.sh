#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSIONS=("3.11" "3.12" "3.13" "3.14")

# Allow overriding which versions to test, e.g.: PYTHON_VERSIONS="3.11 3.12" bash ci.sh
if [[ -n "${TEST_PYTHON_VERSIONS:-}" ]]; then
  read -ra PYTHON_VERSIONS <<< "$TEST_PYTHON_VERSIONS"
fi

passed=()
failed=()

run_for_version() {
  local version="$1"

  # Find a Python binary matching the requested version
  local python_bin
  python_bin=$(command -v "python${version}" 2>/dev/null \
    || command -v "python3" 2>/dev/null \
    || command -v "python" 2>/dev/null || true)

  if [[ -z "$python_bin" ]]; then
    echo "⚠️  Python ${version} not found — skipping"
    return 1
  fi

  # Verify the found binary actually matches the requested version
  local actual_version
  actual_version=$("$python_bin" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  if [[ "$actual_version" != "$version" ]]; then
    if command -v pyenv &>/dev/null; then
      python_bin=$(pyenv prefix "${version}" 2>/dev/null && echo "$(pyenv prefix "${version}")/bin/python" || true)
    fi
    if [[ -z "$python_bin" ]] || ! "$python_bin" --version &>/dev/null; then
      echo "⚠️  Python ${version} not available (found ${actual_version}) — skipping"
      return 1
    fi
  fi

  echo ""
  echo "========================================"
  echo " Testing with Python ${version} (${python_bin})"
  echo "========================================"

  # Create an isolated virtual environment
  local venv_dir=".ci_venv_${version}"
  "$python_bin" -m venv "$venv_dir"
  source "${venv_dir}/bin/activate"

  echo "--- Installing dependencies ---"
  python -m pip install --upgrade pip -q
  pip install -r requirements.txt -q

  echo "--- Running checks (scripts/check.sh) ---"
  bash scripts/check.sh

  echo "--- Running pytest ---"
  pytest tests/ -v --cov=src --cov-fail-under=80

  deactivate
  rm -rf "$venv_dir"
}

for version in "${PYTHON_VERSIONS[@]}"; do
  if run_for_version "$version"; then
    passed+=("$version")
  else
    failed+=("$version")
  fi
done

echo ""
echo "========================================"
echo " CI Summary"
echo "========================================"
echo "✓ Passed: ${passed[*]:-none}"
echo "× Failed: ${failed[*]:-none}"
echo ""

if [[ ${#failed[@]} -gt 0 ]]; then
  exit 1
fi
