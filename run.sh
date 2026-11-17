#!/bin/sh
# Run the installed Unix development environment without touching global Python.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$project_dir/.venv/bin/python" ]; then
    printf '%s\n' 'Create the environment first: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt' >&2
    exit 1
fi
exec "$project_dir/.venv/bin/python" -m rhtop "$@"
