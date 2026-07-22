#!/usr/bin/env bash
set -euo pipefail

MISSION_ID="${MISSION_ID:?MISSION_ID is required}"
RX_SCRIPT="${RX_SCRIPT:?RX_SCRIPT is required}"
TX_SCRIPT="${TX_SCRIPT:-/home/user/rx_sampling/tx_no_gui.py}"
JAMMER_SCRIPT="${JAMMER_SCRIPT:-/home/user/rx_sampling/jam_no_gui.py}"
START_TX="${START_TX:-0}"
START_JAMMER="${START_JAMMER:-0}"
MISSION_STATE_DIR="${MISSION_STATE_DIR:-/var/lib/simworld/capture}"
WORKDIR="${WORKDIR:-/home/user/rx_sampling}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
NOISE_UPLOAD_HELPER="${NOISE_UPLOAD_HELPER:-/home/user/upload_noise_csv.py}"
NOISE_CSV="${NOISE_CSV:-$WORKDIR/noise.csv}"
UPLOAD_API_URL="${UPLOAD_API_URL:-}"
SCENE="${SCENE:-NTPU}"
MAP_TYPE="${MAP_TYPE:-iss}"

MISSION_DIR="${MISSION_STATE_DIR%/}/${MISSION_ID}"
MISSION_NOISE_CSV="${MISSION_DIR}/noise.csv"
STATE_FILE="${MISSION_DIR}/mission.json"
PIDS=()
FINALIZED=0
JOB_STATE="running"
JOB_ERROR=""
CHILD_STOP_TIMEOUT=10
CHILD_KILL_TIMEOUT=2

write_state() {
  local phase="$1"
  local state="$2"
  local upload_state="${3:-recording}"
  local error="${4:-}"
  local temp_file="${STATE_FILE}.tmp.$$"
  mkdir -p "${MISSION_DIR}"
  "${PYTHON_BIN}" - "${temp_file}" "${MISSION_ID}" "${phase}" "${state}" "${upload_state}" "${MISSION_NOISE_CSV}" "${error}" <<'PY'
import json
import sys
from datetime import datetime

path, mission_id, phase, state, upload_state, noise_csv, error = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "mission_id": mission_id,
        "phase": phase,
        "state": state,
        "upload_state": upload_state,
        "noise_csv": noise_csv,
        "error": error,
        "updated_at": datetime.now().astimezone().isoformat(),
    }, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
  mv "${temp_file}" "${STATE_FILE}"
}

start_bg() {
  local label="$1"
  shift
  echo "[pi-radio-stack] starting ${label}: $*"
  "$@" &
  PIDS+=("$!")
}

upload_noise() {
  if [[ ! -s "${MISSION_NOISE_CSV}" || -z "${UPLOAD_API_URL}" ]]; then
    return 1
  fi
  "${PYTHON_BIN}" "${NOISE_UPLOAD_HELPER}" \
    --api-url "${UPLOAD_API_URL}" \
    --scene "${SCENE}" \
    --mission-id "${MISSION_ID}" \
    --noise-csv "${MISSION_NOISE_CSV}" \
    --map-type "${MAP_TYPE}" \
    --auto-simulate-last
}

cleanup() {
  if [[ "${FINALIZED}" == "1" ]]; then
    return
  fi
  FINALIZED=1
  trap - EXIT INT TERM
  write_state "stopping_service" "stopping" "finalizing" "${JOB_ERROR}"
  echo "[pi-radio-stack] stopping child processes"
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done

  local deadline=$((SECONDS + CHILD_STOP_TIMEOUT))
  while (( SECONDS < deadline )); do
    local alive=0
    for pid in "${PIDS[@]:-}"; do
      if kill -0 "${pid}" 2>/dev/null; then alive=1; fi
    done
    if (( alive == 0 )); then break; fi
    sleep 1
  done

  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill -9 "${pid}" 2>/dev/null || true
    fi
  done
  deadline=$((SECONDS + CHILD_KILL_TIMEOUT))
  while (( SECONDS < deadline )); do
    local alive=0
    for pid in "${PIDS[@]:-}"; do
      if kill -0 "${pid}" 2>/dev/null; then alive=1; fi
    done
    if (( alive == 0 )); then break; fi
    sleep 1
  done
  wait || true

  local final_state="${JOB_STATE}"
  if [[ "${final_state}" == "running" ]]; then
    final_state="stopped"
  fi

  write_state "finalizing_file" "${final_state}" "finalizing" "${JOB_ERROR}"
  mkdir -p "${MISSION_DIR}"
  if [[ ! -s "${NOISE_CSV}" ]]; then
    write_state "failed" "failed" "failed" "noise.csv is missing or empty"
    exit 1
  fi
  if ! cp "${NOISE_CSV}" "${MISSION_NOISE_CSV}"; then
    write_state "failed" "failed" "failed" "failed to copy noise.csv"
    exit 1
  fi
  write_state "upload_pending" "${final_state}" "upload_pending" "${JOB_ERROR}"
}

trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

mkdir -p "${MISSION_DIR}"
cd "${WORKDIR}"
write_state "starting_service" "starting" "recording"

start_bg "rx" "${PYTHON_BIN}" "${RX_SCRIPT}"
if [[ "${START_TX}" == "1" ]]; then
  start_bg "tx" "${PYTHON_BIN}" "${TX_SCRIPT}"
fi
if [[ "${START_JAMMER}" == "1" ]]; then
  start_bg "jammer" "${PYTHON_BIN}" "${JAMMER_SCRIPT}"
fi

write_state "recording" "running" "recording"

set +e
wait -n
EXIT_CODE=$?
set -e
if [[ "${EXIT_CODE}" -ne 0 ]]; then
  JOB_STATE="failed"
  JOB_ERROR="capture child exited with ${EXIT_CODE}"
fi
exit "${EXIT_CODE}"
