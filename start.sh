#!/usr/bin/env bash
# Bug Buster launcher for Mac/Linux:  ./start.sh   (first time: chmod +x start.sh)
# First run installs everything (a few minutes). Later runs start in seconds.
set -e
cd "$(dirname "$0")"
MODEL="gemma3:4b"

command -v ollama >/dev/null 2>&1 || { echo "Ollama is not installed. Get it from https://ollama.com and run this again."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is not installed. Get it from https://www.python.org and run this again."; exit 1; }

if [ ! -x backend/.venv/bin/python ]; then
  echo "[1/4] Creating Python environment..."
  python3 -m venv backend/.venv
fi
if [ ! -f backend/.venv/.installed ]; then
  echo "[2/4] Installing backend packages (first run only)..."
  backend/.venv/bin/python -m pip install -q -r backend/requirements.txt
  touch backend/.venv/.installed
fi
[ -f backend/.env ] || cp backend/.env.example backend/.env

echo "[3/4] Checking Ollama and the $MODEL model..."
OLLAMA_PID=""
if ! ollama list >/dev/null 2>&1; then
  ollama serve >/tmp/bugbuster-ollama.log 2>&1 &
  OLLAMA_PID=$!
  sleep 5
fi
if ! ollama list | grep -q "$MODEL"; then
  echo "Downloading $MODEL (about 3 GB, first run only)..."
  ollama pull "$MODEL"
fi

echo "[4/4] Starting Bug Buster..."
(cd backend && exec .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000) &
BACK_PID=$!
(cd frontend && exec ../backend/.venv/bin/python -m http.server 5500) &
FRONT_PID=$!

cleanup() {
  kill "$BACK_PID" "$FRONT_PID" $OLLAMA_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 4
if command -v open >/dev/null 2>&1; then open http://localhost:5500
elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:5500 >/dev/null 2>&1 || true
fi

echo
echo "Bug Buster is running at http://localhost:5500"
echo "Press Ctrl+C to stop everything."
wait
