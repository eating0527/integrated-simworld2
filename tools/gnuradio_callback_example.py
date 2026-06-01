import json
from pathlib import Path

from gnuradio_to_simulator import send_measurement


DEVICES_FILE = Path(__file__).with_name("simulator_devices.example.json")


def upload_measurement(
    scene: str,
    lat: float,
    lon: float,
    alt: float,
    mean_power_dbfs: float,
    peak_power_dbfs: float,
    sample_count: int,
    center_freq_hz: float,
    sample_rate_hz: float,
    auto_simulate: bool = True,
    map_type: str = "iss",
) -> dict:
    devices = json.loads(DEVICES_FILE.read_text(encoding="utf-8")) if DEVICES_FILE.exists() else []
    payload = {
        "scene": scene,
        "device_id": "usrp-b210-sensor",
        "device_name": "USRP B210 Sensor",
        "device_type": "uav",
        "role": "rx",
        "lat": lat,
        "lon": lon,
        "alt": alt,
        "center_freq_hz": center_freq_hz,
        "sample_rate_hz": sample_rate_hz,
        "sample_count": sample_count,
        "mean_power_dbfs": mean_power_dbfs,
        "peak_power_dbfs": peak_power_dbfs,
        "auto_simulate": auto_simulate,
        "map_type": map_type,
        "devices": devices,
    }
    return send_measurement(payload)


if __name__ == "__main__":
    response = upload_measurement(
        scene="NTPU",
        lat=24.9438,
        lon=121.3687,
        alt=30.0,
        mean_power_dbfs=-42.1,
        peak_power_dbfs=-18.3,
        sample_count=200000,
        center_freq_hz=2.45e9,
        sample_rate_hz=1e6,
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
