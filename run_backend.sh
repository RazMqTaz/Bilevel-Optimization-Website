#!/usr/bin/env bash
# Run the backend using the project's virtualenv so uvicorn and FastAPI use the same Python.
# (Running plain "uvicorn" from pipx uses Python 3.14 and won't see packages installed in the project.)

set -e
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Creating .venv and installing dependencies..."
  python3 -m venv .venv
  .venv/bin/pip install -e .
fi

.venv/bin/python -m uvicorn backend.main:app --reload
