#!/usr/bin/env bash
# Everything CI runs, in one place. Any CI system only needs uv installed and
# to call this script; run it locally to reproduce a CI failure.
set -euo pipefail

cd "$(dirname "$0")/.."

# Supported Python versions. Keep in sync with `requires-python` and the
# classifiers in pyproject.toml.
pythons=(3.12 3.13 3.14)

echo "--- uv sync"
uv sync --locked

echo "--- static checks (pre-commit)"
uv run --locked pre-commit run --all-files --show-diff-on-failure

for py in "${pythons[@]}"; do
    echo "--- tests + coverage on Python ${py}"
    # --isolated: throwaway environment per interpreter; .venv is untouched.
    uv run --locked --isolated --python "${py}" pytest --cov
done

echo "--- dependency vulnerability audit"
# `uv audit` is experimental; the flag acknowledges that and silences the
# warning. It checks uv.lock against the OSV database, so it needs network.
uv audit --locked --preview-features audit-command
