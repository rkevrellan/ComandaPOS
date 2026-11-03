#!/usr/bin/env sh
# ComandaPOS - inicio en Mac/Linux. La primera vez crea el entorno e instala todo.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Creando el entorno de Python..."
  python3 -m venv .venv
fi
echo "Revisando dependencias..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
exec .venv/bin/python run.py "$@"
