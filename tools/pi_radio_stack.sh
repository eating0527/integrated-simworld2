#!/usr/bin/env bash
set -euo pipefail

WORKDIR="${WORKDIR:-/home/user/digitaltwin-modulation/USRP_transmit/noise_detect}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
RX_SCRIPT="${RX_SCRIPT:-$WORKDIR/chan_est_rx.py}"
TX_SCRIPT="${TX_SCRIPT:-$WORKDIR/chan_est_tx.py}"
JAMMER_SCRIPT="${JAMMER_SCRIPT:-$WORKDIR/noise.py}"
NOISE_LOGGER_SCRIPT="${NOISE_LOGGER_SCRIPT:-/home/user/zmq_to_noise_csv.py}"
NOISE_CSV="${NOISE_CSV:-$WORKDIR/noise.csv}"
START_NOISE_LOGGER="${START_NOISE_LOGGER:-1}"
START_NOISE_UPLOADER="${START_NOISE_UPLOADER:-0}"
NOISE_UPLOADER_SCRIPT="${NOISE_UPLOADER_SCRIPT:-/home/user/watch_and_upload_noise.py}"
NOISE_UPLOADER_ARGS="${NOISE_UPLOADER_ARGS:-}"

PIDS=()

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

cleanup() {
  echo "[pi-radio-stack] stopping child processes"
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  wait || true
}

trap cleanup EXIT INT TERM

cd "${WORKDIR}"

start_gui "rx" "${RX_SCRIPT}"
sleep 2
start_gui "tx" "${TX_SCRIPT}"
sleep 2
start_gui "jammer" "${JAMMER_SCRIPT}"

if [[ "${START_NOISE_LOGGER}" == "1" ]]; then
  sleep 2
  start_bg "noise-csv-logger" "${PYTHON_BIN}" "${NOISE_LOGGER_SCRIPT}" --noise-csv "${NOISE_CSV}"
fi

if [[ "${START_NOISE_UPLOADER}" == "1" ]]; then
  sleep 2
  # shellcheck disable=SC2206
  EXTRA_ARGS=(${NOISE_UPLOADER_ARGS})
  start_bg "noise-uploader" "${PYTHON_BIN}" "${NOISE_UPLOADER_SCRIPT}" "${EXTRA_ARGS[@]}"
fi

wait -n
