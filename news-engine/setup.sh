#!/usr/bin/env bash
# Instalacion desde cero. Idempotente: se puede correr las veces que haga falta.
#
#   ./setup.sh          instala, crea la base y verifica
#   ./setup.sh --demo   ademas corre la demo con datos sinteticos
set -euo pipefail

cd "$(dirname "$0")"

PY=${PYTHON:-python3.11}
command -v "$PY" >/dev/null 2>&1 || PY=python3

echo "==> Entorno virtual"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip

echo "==> Dependencias"
.venv/bin/pip install --quiet \
  "pydantic>=2.6" "typer>=0.12" "httpx>=0.27" \
  "pyyaml>=6.0" "python-dotenv>=1.0" "rich>=13.7" \
  "pytest>=8.0" "freezegun>=1.4"

# Las de las tareas 6 en adelante (estadistica, embeddings) todavia no se usan.
# Se instalan con --full para no bajar 2 GB de torch a quien solo quiere probar.
if [ "${1:-}" = "--full" ]; then
  echo "==> Dependencias pesadas (estadistica y embeddings)"
  .venv/bin/pip install --quiet \
    "pandas>=2.2" "numpy>=1.26" "scipy>=1.12" "statsmodels>=0.14" \
    "sentence-transformers>=2.7" "yfinance>=0.2.40" "feedparser>=6.0" "jinja2>=3.1"
fi

echo "==> Credenciales"
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "    creado .env desde el ejemplo. Cargale FRED_API_KEY antes de bajar macro."
fi

echo "==> Base de datos"
.venv/bin/python run.py db init

echo "==> Tests"
.venv/bin/python -m pytest tests/ -q

echo "==> Guardas anti-look-ahead"
.venv/bin/python run.py pit verify

if [ "${1:-}" = "--demo" ]; then
  echo "==> Demo con datos sinteticos"
  .venv/bin/python run.py demo
fi

echo
echo "Listo. Diagnostico:"
echo "    source .venv/bin/activate && python run.py doctor"
