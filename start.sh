#!/usr/bin/env bash
# GPS Tracker startup script (Windows-compatible)
# Usage: bash start.sh
#        bash start.sh --no-tunnel

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
USE_TUNNEL=true

[[ -f "$SCRIPT_DIR/.env" ]] && source "$SCRIPT_DIR/.env"

for arg in "$@"; do
  case $arg in
    --no-tunnel) USE_TUNNEL=false ;;
  esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

[[ -d "$BACKEND_DIR/.venv" ]] || { error "Missing .venv, run: cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt"; exit 1; }
[[ -d "$FRONTEND_DIR/node_modules" ]] || { error "Missing node_modules, run: cd frontend && npm install"; exit 1; }

LOG_DIR="$SCRIPT_DIR/.logs"
mkdir -p "$LOG_DIR"

PIDS=()

cleanup() {
  echo ""
  info "Stopping all services..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null || true
  done
  info "All stopped."
  exit 0
}
trap cleanup SIGINT SIGTERM

if [[ -f "$BACKEND_DIR/.venv/Scripts/uvicorn.exe" ]]; then
  UVICORN_CMD="$BACKEND_DIR/.venv/Scripts/uvicorn.exe"
elif [[ -f "$BACKEND_DIR/.venv/Scripts/uvicorn" ]]; then
  UVICORN_CMD="$BACKEND_DIR/.venv/Scripts/uvicorn"
else
  UVICORN_CMD="$BACKEND_DIR/.venv/bin/uvicorn"
fi

NPM_CMD="$(command -v npm.cmd 2>/dev/null || command -v npm 2>/dev/null || echo npm)"

info "Starting backend (port 8000)..."
"$UVICORN_CMD" app.main:app \
  --host 0.0.0.0 --port 8000 --reload \
  --app-dir "$BACKEND_DIR" \
  > "$LOG_DIR/backend.log" 2>&1 &
PIDS+=($!)
info "   Backend PID: ${PIDS[-1]}  log: .logs/backend.log"

sleep 2

info "Starting frontend (port 5173)..."
(cd "$FRONTEND_DIR" && "$NPM_CMD" run dev) \
  > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=($!)
info "   Frontend PID: ${PIDS[-1]}  log: .logs/frontend.log"

TUNNEL_STARTED=false
if $USE_TUNNEL; then
  CF_BIN="$(command -v cloudflared 2>/dev/null \
    || command -v cloudflared.exe 2>/dev/null \
    || ls "/mnt/c/Program Files/cloudflared/cloudflared.exe" 2>/dev/null \
    || ls "/mnt/c/Users/503/AppData/Local/Microsoft/WinGet/Packages/Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe/cloudflared.exe" 2>/dev/null \
    || true)"

  if [[ -x "$CF_BIN" ]]; then
    info "Starting Cloudflare Tunnel..."
    TOKEN="$(grep '^CLOUDFLARED_TOKEN=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2-)"
    if [[ -n "$TOKEN" ]]; then
      "$CF_BIN" tunnel --protocol http2 run --token "$TOKEN" \
        > "$LOG_DIR/tunnel.log" 2>&1 &
    else
      "$CF_BIN" tunnel run simworld2 \
        > "$LOG_DIR/tunnel.log" 2>&1 &
    fi
    PIDS+=($!)
    TUNNEL_STARTED=true
    info "   Tunnel PID: ${PIDS[-1]}  log: .logs/tunnel.log"
  else
    warn "cloudflared not found, skipping tunnel"
  fi
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "  Frontend : ${YELLOW}http://localhost:5173${NC}"
$USE_TUNNEL && echo -e "  Public   : ${YELLOW}https://frontend.simworld.website${NC}"
echo -e "  Press Ctrl+C to stop all services"
echo -e "${GREEN}============================================${NC}"
echo ""

LOG_FILES=("$LOG_DIR/backend.log" "$LOG_DIR/frontend.log")
$TUNNEL_STARTED && LOG_FILES+=("$LOG_DIR/tunnel.log")
tail -f "${LOG_FILES[@]}" &
PIDS+=($!)

wait
