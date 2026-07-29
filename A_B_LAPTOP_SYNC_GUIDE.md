# A/B Laptop Sync Guide

This guide is for the two-location setup:

```text
A site laptop receives AP3/controller UAV GPS.
A site laptop writes local gps.csv.
A site laptop streams GPS points to B site backend through Cloudflare.
USRP noise.csv uploads to both A and B backends.
B site laptop serves the public frontend for remote viewing.
```

## Roles

```text
A laptop: AP3/controller + UAV GPS + local backend/frontend, no Cloudflare tunnel.
B laptop: backend + frontend + Cloudflare tunnel, no AP3/controller.
```

Do not run the same Cloudflare tunnel on both A and B. Keep `backend.simworld.website` pointing to B.

## A Laptop Setup

In A laptop `.env`:

```dotenv
GPS_SYNC_API_URL=https://backend.simworld.website/api/usrp/sync-gps-point
USRP_UPLOAD_API_URLS=http://<A laptop IPv4>:8888/api/usrp/upload-noise-csv,https://backend.simworld.website/api/usrp/upload-noise-csv
```

Use A laptop's LAN IPv4 for the first `USRP_UPLOAD_API_URLS` entry, because the Pi/USRP is at A site.

Start A:

```powershell
cd C:\Users\user\projects\integrated-sim-world2\integrated-simworld2
.\start.ps1 -NoTunnel
```

A local UI:

```text
http://localhost:5173
```

## B Laptop Startup

Start B:

```powershell
cd C:\Users\user\projects\integrated-sim-world2\integrated-simworld2
.\start.ps1 -NoAP3
```

B runs the public tunnel. Remote users open:

```text
https://frontend.simworld.website
```

B startup automatically checks recent incoming A-site missions and prints the latest mission id:

```text
A-site latest mission id: flight_001
GPS received: True  Noise received: True
Logs: https://backend.simworld.website/api/usrp/gps-sync/logs?mission_id=flight_001
```

If A has not sent data yet, B prints:

```text
A-site mission lookup: no incoming GPS/noise missions yet.
```

## Manual Checks

List recent missions received by B:

```text
https://backend.simworld.website/api/usrp/gps-sync/missions
```

Check GPS sync logs for one mission:

```text
https://backend.simworld.website/api/usrp/gps-sync/logs?mission_id=<mission-id>
```

B stores received files here:

```text
incoming\<mission-id>\gps.csv
incoming\<mission-id>\gps_sync.log
incoming\<mission-id>\noise.csv
```

For ISS_UNET Noise with GPS on B, wait until the mission list shows:

```text
has_gps: true
has_noise: true
```

## Quick GPS-Only Test

On A, without running the full startup script:

```powershell
cd C:\Users\user\projects\integrated-sim-world2\integrated-simworld2
.\backend\.venv\Scripts\python tools\ap3_to_gps_csv.py `
  --mission-id flight_001 `
  --incoming-dir incoming `
  --sync-api-url https://backend.simworld.website/api/usrp/sync-gps-point
```

## Common Issues

If B frontend does not show the route, first check:

```text
https://backend.simworld.website/api/usrp/gps-sync/missions
```

If the mission API has data, A to B sync is working and the issue is probably frontend WebSocket or display state.

If the mission API has no data, confirm A has:

```dotenv
GPS_SYNC_API_URL=https://backend.simworld.website/api/usrp/sync-gps-point
```

Also confirm B is running:

```powershell
.\start.ps1 -NoAP3
```
