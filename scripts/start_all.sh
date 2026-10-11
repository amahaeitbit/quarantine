#!/usr/bin/env bash
# Start the gateway, Guardian, Evolver and console. Ctrl-C stops all of them.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
export PYTHONPATH=src PYTHONUNBUFFERED=1
mkdir -p logs

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

$PY src/quarantine/gateway.py > logs/gateway.log 2>&1 &
pids+=($!)
$PY -m quarantine.guardian > logs/guardian.log 2>&1 &
pids+=($!)
$PY -m quarantine.evolver > logs/evolver.log 2>&1 &
pids+=($!)
$PY -m streamlit run console/app.py --server.headless true --server.port 8501 > logs/console.log 2>&1 &
pids+=($!)

echo "gateway   http://localhost:8000/mcp"
echo "console   http://localhost:8501"
echo "logs      logs/gateway.log  logs/guardian.log  logs/evolver.log  logs/console.log"
echo "Ctrl-C stops everything."
wait
