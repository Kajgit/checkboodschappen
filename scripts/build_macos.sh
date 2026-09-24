#!/bin/sh
set -eu
PYTHON="${VIRTUAL_ENV:-.venv}/bin/python"
PYINSTALLER="${VIRTUAL_ENV:-.venv}/bin/pyinstaller"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/.pyinstaller-cache}"
test -x "$PYINSTALLER" || "$PYTHON" -m pip install pyinstaller
"$PYINSTALLER" --noconfirm --windowed --name "BoodschappenWijzer" \
  --add-data "app/static:app/static" \
  --hidden-import app.main run.py
echo "App gebouwd in dist/BoodschappenWijzer.app"
