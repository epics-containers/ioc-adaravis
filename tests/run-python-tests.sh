#!/bin/bash

set -xe

THIS=$(realpath $(dirname $0))
ROOT=$(realpath ${THIS}/..)

uv venv --python python3.13 --allow-existing

uv pip install -r requirements.txt
uv pip install -r requirements-dev.txt

uv run pytest $ROOT/python-tests