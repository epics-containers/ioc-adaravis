#!/bin/bash

set -xe

THIS=$(realpath $(dirname $0))
ROOT=$(realpath ${THIS}/..)

if [ -z "$VIRTUAL_ENV" ] && [ -z "$UV_PYTHON_INSTALL_DIR" ]; then
    uv venv --python python3.13 --allow-existing
    uv pip install -r requirements.txt
fi

uv pip install -r requirements-dev.txt

uv run pytest $ROOT/python-tests