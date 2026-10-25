#!/usr/bin/env bash
set -eo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# 1. Parse arguments
CHECK_ONLY=false
for arg in "$@"; do
  if [ "$arg" = "--check-only" ]; then
    CHECK_ONLY=true
  fi
done

# 2. Load .env and .env.local if present
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  source "$REPO_ROOT/.env"
  set +a
fi

if [ -f "$REPO_ROOT/.env.local" ]; then
  set -a
  source "$REPO_ROOT/.env.local"
  set +a
fi

# 3. Mode announcement based on GEMINI_API_KEY
if [ -n "${GEMINI_API_KEY:-}" ] || [ -n "${GOOGLE_API_KEY:-}" ]; then
  echo "========================================================================"
  echo "   GridPilot Live Ops: MODO VIVO (Gemini 4 Argon)"
  echo "========================================================================"
else
  echo "========================================================================"
  echo "   GridPilot Live Ops: MODO OFFLINE (Fixture Replay)"
  echo "========================================================================"
fi

# 4. Resolve binaries
export PATH="/opt/anaconda3/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

if command -v uvicorn >/dev/null 2>&1; then
  UVICORN_CMD="uvicorn"
elif [ -x "/opt/anaconda3/bin/uvicorn" ]; then
  UVICORN_CMD="/opt/anaconda3/bin/uvicorn"
else
  UVICORN_CMD="python3 -m uvicorn"
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
elif [ -x "/opt/anaconda3/bin/python3" ]; then
  PYTHON_CMD="/opt/anaconda3/bin/python3"
else
  PYTHON_CMD="python"
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  local exit_code=$?
  trap - SIGINT SIGTERM EXIT
  if [ "$CHECK_ONLY" = "true" ]; then
    echo "Check finalizado (código $exit_code)."
  else
    echo "GridPilot: cerrando procesos..."
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
  exit $exit_code
}

trap cleanup SIGINT SIGTERM EXIT

# 5. Start Backend
echo "Iniciando backend FastAPI..."
if [ "$CHECK_ONLY" = "true" ]; then
  $UVICORN_CMD backend.main:create_app --factory --host 127.0.0.1 --port 8000 >/dev/null 2>&1 &
  BACKEND_PID=$!
else
  $UVICORN_CMD backend.main:create_app --factory --host 127.0.0.1 --port 8000 &
  BACKEND_PID=$!
fi

# 6. Start Frontend if not check-only
if [ "$CHECK_ONLY" != "true" ]; then
  echo "Iniciando frontend Vite..."
  npm --prefix frontend run dev -- --port 5173 &
  FRONTEND_PID=$!
fi

# 7. Wait for /api/health (up to 15s)
HEALTH_URL="http://127.0.0.1:8000/api/health"
READY=false
START_TIME=$(date +%s)
TIMEOUT=15

while [ $(($(date +%s) - START_TIME)) -lt $TIMEOUT ]; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: El backend finalizó prematuramente." >&2
    exit 1
  fi
  if HEALTH_JSON=$(curl -s -f "$HEALTH_URL" 2>/dev/null); then
    if echo "$HEALTH_JSON" | grep -q '"status":"ok"'; then
      READY=true
      break
    fi
  fi
  sleep 0.5
done

if [ "$READY" != "true" ]; then
  echo "ERROR: Timeout esperando backend en $HEALTH_URL tras ${TIMEOUT}s" >&2
  exit 1
fi

# 8. Print Status Banner
"$PYTHON_CMD" -c "
import json, sys

try:
    data = json.loads(sys.argv[1])
except Exception:
    data = {}

mode = str(data.get('mode', 'offline')).upper()
solver_status = 'OK' if data.get('solver_ok') else 'FAIL'
gemini_status = 'CONFIGURADO' if data.get('gemini_credentials_configured') else 'NO CONFIGURADO (Offline)'
agent_model = data.get('gemini_model_agent', 'gemini-4-argon')
fast_model = data.get('gemini_model_fast', 'gemini-2.5-flash')

banner = f'''
========================================================================
                      GRIDPILOT LIVE OPS - DEMO                         
========================================================================
 Backend Health:
   - Modo:               {mode}
   - Solver (HiGHS):     {solver_status}
   - Gemini API:         {gemini_status}
   - Modelo Agente:      {agent_model}
   - Modelo Rápido:      {fast_model}

 URLs de Acceso:
   - Sala de Control:    http://localhost:5173/
   - Vista Explicativa:  http://localhost:5173/explicar
   - Consola Dev:        http://localhost:5173/dev
   - Página del Jurado:  http://localhost:5173/jurado
   - QR SVG:             http://localhost:8000/api/live/sessions/demo/qr.svg
========================================================================
'''
print(banner)
" "$HEALTH_JSON"

if [ "$CHECK_ONLY" = "true" ]; then
  exit 0
fi

# 9. Wait for child processes
wait
