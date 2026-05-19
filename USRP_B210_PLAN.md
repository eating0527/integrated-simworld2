# USRP B210 Integration Plan

## Goal

Integrate a `USRP B210` RF sensing pipeline with this simulator project so measured RF data can be associated with UAV position and visualized in the simulator.

The current target is:

- `RX side`: a `USRP B210` used as the airborne or local receiver
- `TX side`: a separate `USRP B210` controlled by us for legal, known test transmissions
- `Simulator side`: this repo receives processed RF summaries through the existing WebSocket backend

## Current status

The local Windows machine has already been validated for basic `B210` operation:

- Windows detects the device as `Ettus Research LLC B200/B210`
- `UHD` is installed locally
- `uhd_find_devices` can see the B210
- `uhd_usrp_probe --args "type=b200"` succeeds
- `benchmark_rate` succeeds at `1 Msps`
- short capture tests succeed through `rx_samples_to_file`

This means:

- the hardware is recognized
- USB 3.0 is working
- firmware/FPGA loading is working
- sample capture is working

## What is already implemented in this repo

There is now a basic bridge script:

- [tools/usrp_to_simulator.py](/C:/Users/user/projects/integrated-sim-world2/integrated-simworld2/tools/usrp_to_simulator.py)

This script currently:

- captures a short block of IQ samples from the B210
- computes simple RF summary metrics
- sends GPS-style position updates to `/ws/gps`
- sends a `usrp-spectrum` message to the simulator WebSocket

The backend already supports this because `/ws/gps` forwards arbitrary JSON messages.

The frontend now also has a basic USRP telemetry panel:

- [frontend/src/components/ui/USRPTelemetry.tsx](/C:/Users/user/projects/integrated-sim-world2/integrated-simworld2/frontend/src/components/ui/USRPTelemetry.tsx)

## What the current bridge measures

The current bridge does not decode packets or content. It only computes RF-level summaries from real captured IQ data:

- `center_freq_hz`
- `sample_rate_hz`
- `gain_db`
- `sample_count`
- `capture_seconds`
- `mean_power_dbfs`
- `peak_power_dbfs`
- `rms_dbfs`
- `max_iq_abs`

These are real measurements from the B210 receiver, but they are not yet demodulated payload data.

## Architecture options

### Option A: Live streaming to simulator

Path:

`USRP B210 -> companion computer / laptop -> local processing -> WebSocket -> simulator`

Pros:

- immediate visualization
- easier interactive debugging

Cons:

- needs a reliable network path
- raw IQ is too heavy for practical live transmission
- should only send processed summaries or decoded packet results

### Option B: Offline logging then import

Path:

`USRP B210 -> local storage -> post-flight/offline processing -> simulator import`

Pros:

- more robust
- no live Wi-Fi dependency
- easier to capture larger datasets

Cons:

- not real-time
- needs an import or replay workflow

For UAV use, this is currently the safer path.

## UAV deployment notes

If the B210 is mounted on the UAV with a Raspberry Pi:

- the Pi must provide stable `USB 3.0`
- the Pi must have stable power and thermal headroom
- the Pi should process or summarize data locally
- avoid trying to send raw high-rate IQ over the flight link

Recommended data sent back from UAV:

- timestamp
- GPS position
- altitude
- center frequency
- sample rate
- power summary
- FFT peak / band energy summary
- event detection result

## Important constraint

We should not depend on the drone vendor's original control link for custom data transport.

Use one of these instead:

- separate Wi-Fi
- 4G/5G hotspot or modem
- Ethernet while bench testing
- offline logging

## Known good next steps

The recommended development path is:

1. keep using the current B210 RX summary bridge
2. add FFT-based spectrum summary
3. add CSV or JSON logging for every capture
4. add replay/import support for offline datasets
5. introduce our own TX waveform with the second B210
6. add demodulation only for our own known waveform

## TX/RX plan

Because a second `USRP B210` will be used as the transmitter, we can build a legal, known SDR test chain.

Recommended phased approach:

### Phase 1: RF presence check

Transmit from our TX B210:

- CW tone

Receive on RX B210:

- verify FFT peak
- verify received power response
- verify geometry changes affect measured power

### Phase 2: Simple digital link

Transmit from our TX B210:

- simple `OOK`, `BPSK`, or `QPSK` packets

Receive on RX B210:

- detect preamble
- recover symbol timing
- demodulate payload
- compute packet success/failure

### Phase 3: Simulator integration

Send to simulator:

- transmitter ID
- receiver ID
- timestamp
- center frequency
- received power
- SNR-like metrics
- packet success
- decoded payload summary
- UAV position

## Recommended immediate next implementation

The next code change should be one of these:

1. add FFT output to `tools/usrp_to_simulator.py`
2. add CSV/JSON logging to `tools/usrp_to_simulator.py`
3. add a replay script that reads logged RF summaries and feeds them into `/ws/gps`

Best next choice:

- `FFT + CSV logging`

That gives real analysis value without committing yet to a full demodulator.

## Current command example

Example local test:

```powershell
backend\.venv\Scripts\python.exe .\tools\usrp_to_simulator.py `
  --websocket-url ws://127.0.0.1:8888/ws/gps `
  --device-id align-m4p-top-aircraft `
  --device-name "M4P TOP + B210" `
  --center-freq 2450000000 `
  --sample-rate 1000000 `
  --gain 20 `
  --lat 24.784727 `
  --lon 121.000433 `
  --alt 120
```

## Summary

What is already true:

- B210 capture works
- the simulator bridge path exists
- the simulator can display basic RF summary telemetry

What is not done yet:

- FFT visualization
- structured logging
- offline replay/import
- custom TX waveform definition
- demodulation of our own packets

The project is in a good state to continue from RF summary sensing into our own TX/RX SDR test link.
