#!/bin/zsh
set -eu
cd -- "${0:A:h}"
exec "${IELTS_PYTHON:-.venv/bin/python}" app.py
