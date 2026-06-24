#!/usr/bin/env bash
set -euo pipefail

MISSION_ID="${MISSION_ID:?MISSION_ID is required}"
MISSION_STATE_DIR="${MISSION_STATE_DIR:-/var/lib/simworld/capture}"
WORKDIR="${WORKDIR:-/home/user/digitaltwin-modulation/USRP_transmit/noise_detect}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
RX_SCRIPT="${RX_SCRIPT:-$WORKDIR/chan_est_rx.py}"
TX_SCRIPT="${TX_SCRIPT:-$WORKDIR/chan_est_tx.py}"
JAMMER_SCRIPT="${JAMMER_SCRIPT:-$WORKDIR/noise.py}"
NOISE_LOGGER_SCRIPT="${NOISE_LOGGER_SCRIPT:-/home/user/zmq_to_noise_csv.py}"
NOISE_UPLOAD_HELPER="${NOISE_UPLOAD_HELPER:-/home/user/upload_noise_csv.py}"
NOISE_CSV="${NOISE_CSV:-$WORKDIR/noise.csv}"
UPLOAD_API_URL="${UPLOAD_API_URL:-}"
SCENE="${SCENE:-NTPU}"
MAP_TYPE="${MAP_TYPE:-iss}"
START_NOISE_LOGGER="${START_NOISE_LOGGER:-1}"

MISSION_DIR="${MISSION_STATE_DIR%/}/${MISSION_ID}"
STATE_FILE="${MISSION_DIR}/mission.json"
PIDS=()
FINALIZED=0
JOB_STATE="running"
JOB_ERROR=""

write_state() {
  local state="$1"
  local upload_state="${2:-recording}"
  local error="${3:-}"
  local temp_file="${STATE_FILE}.tmp"
  mkdir -p "${MISSION_DIR}"
  printf '{\n  "mission_id": "%s",\n  "state": "%s",\n  "upload_state": "%s",\n  "noise_csv": "%s",\n  "error": "%s",\n  "updated_at": "%s"\n}\n' \
    "${MISSION_ID}" "${state}" "${upload_state}" "${NOISE_CSV}" "${error}" "$(date -Iseconds)" \
    > "${temp_file}"
  mv "${temp_file}" "${STATE_FILE}"
}

start_gui() {
  local label="$1"
  local script_path="$2"
  echo "[pi-radio-stack] starting ${label}: ${script_path}"
  xvfb-run -a "${PYTHON_BIN}" "${script_path}" &
  PIDS+=("$!")
}

start_bg() {
  local label="$1"
  shift
  echo "[pi-radio-stack] starting ${label}: $*"
  "$@" &
  PIDS+=("$!")
}

upload_noise() {
  if [[ ! -s "${NOISE_CSV}" || -z "${UPLOAD_API_URL}" ]]; then
    return 1
  fi
  "${PYTHON_BIN}" "${NOISE_UPLOAD_HELPER}" \
    --api-url "${UPLOAD_API_URL}" \
    --scene "${SCENE}" \
    --mission-id "${MISSION_ID}" \
    --noise-csv "${NOISE_CSV}" \
    --map-type "${MAP_TYPE}" \
    --auto-simulate-last
}

cleanup() {
  if [[ "${FINALIZED}" == "1" ]]; then
    return
  fi
  FINALIZED=1
  trap - EXIT INT TERM
  write_state "finalizing" "finalizing" "${JOB_ERROR}"
  echo "[pi-radio-stack] stopping child processes"
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait || true

  local final_state="${JOB_STATE}"
  if [[ "${final_state}" == "running" ]]; then
    final_state="stopped"
  fi
  if upload_noise; then
    write_state "${final_state}" "uploaded" "${JOB_ERROR}"
  else
    write_state "${final_state}" "upload_pending" "${JOB_ERROR}"
  fi
}

trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

mkdir -p "${MISSION_DIR}"
cd "${WORKDIR}"
write_state "starting" "recording"

start_gui "rx" "${RX_SCRIPT}"
sleep 2
start_gui "tx" "${TX_SCRIPT}"
sleep 2
start_gui "jammer" "${JAMMER_SCRIPT}"

if [[ "${START_NOISE_LOGGER}" == "1" ]]; then
  sleep 2
  start_bg "noise-csv-logger" "${PYTHON_BIN}" "${NOISE_LOGGER_SCRIPT}" --noise-csv "${NOISE_CSV}"
fi

write_state "running" "recording"

set +e
wait -n
EXIT_CODE=$?
set -e
if [[ "${EXIT_CODE}" -ne 0 ]]; then
  JOB_STATE="failed"
  JOB_ERROR="capture child exited with ${EXIT_CODE}"
fi
exit "${EXIT_CODE}"
