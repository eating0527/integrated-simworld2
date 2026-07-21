# Unified Local ENU Coordinate Frame Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mixed GPS/Three.js/Sionna/ISS-UNet coordinate behavior with one SceneFrame-based Local ENU contract, including per-point GPS replay altitude and regenerated 512m NTPU/NYCU assets.

**Architecture:** Backend and frontend each implement a small adapter against the same JSON SceneFrame contract. APIs carry raw GPS or ENU; Three.js, Sionna, and grid row/col conversion happen only at their boundaries. The hard map extent is always 512m square, while frontend display permits a 32m margin without clamping.

**Tech Stack:** Python 3.11, FastAPI, unittest, TypeScript, React, Vitest, Three.js, Blender scene generator, Sionna/ISS-UNet existing services.

---

## Files and ownership

- Create `backend/app/coordinate_frame.py`: immutable frame constants, validation, GPS↔ENU, ENU↔grid, ENU↔Sionna.
- Create `backend/tests/test_coordinate_frame.py`: backend transform contract tests.
- Create `frontend/src/types/sceneFrame.ts`: frontend SceneFrame and ENU types.
- Modify `frontend/src/utils/geo.ts`: GPS↔ENU and ENU↔Three.js only.
- Modify `frontend/tests/geo.test.mjs`: frontend transform and altitude tests.
- Modify `backend/app/blender_generate_scene.py`: fixed frame metadata, 512m bounds, and exported asset frame.
- Modify `backend/app/iss_unet_dataset_service.py`: fixed grid bounds and clipping.
- Modify `backend/app/iss_real.py`: ENU route payloads, fixed grid projection, altitude mode.
- Modify `backend/app/iss_unet_service.py`: ENU/CFAR payloads and frame validation.
- Modify `backend/app/sionna_service_lite.py` and `backend/app/main.py`: ENU inputs only; remove direct Three.js→Sionna conversion.
- Modify `backend/app/scene_index.py` or the existing generated-scene metadata path in `backend/app/main.py`: expose and validate frame metadata.
- Modify `frontend/src/hooks/useGeneratedScene.ts`, `frontend/src/App.tsx`, `frontend/src/types/heatmap.ts`, `frontend/src/types/cfar.ts`, and scene overlays: consume ENU and SceneFrame.
- Modify `tools/ap3_to_gps_csv.py`, `tools/ap3_to_simulator.py`, and GPS parser tests: preserve `alt_mode`.
- Modify affected backend/frontend tests and add one shared fixture under `tests/fixtures/scene-frame.json` if the existing test layout permits it.

### Task 1: Add the backend SceneFrame contract first

**Files:**
- Create: `backend/app/coordinate_frame.py`
- Create: `backend/tests/test_coordinate_frame.py`

- [ ] **Step 1: Write failing tests for the contract**

```python
from app.coordinate_frame import (
    SceneFrame,
    enu_to_grid,
    enu_to_sionna,
    enu_to_three,
    gps_to_enu,
    grid_to_enu,
)


def test_origin_and_axis_directions_are_stable():
    frame = SceneFrame(origin_lat=24.0, origin_lon=121.0, origin_alt_m=100.0)
    assert gps_to_enu(24.0, 121.0, 100.0, frame) == (0.0, 0.0, 0.0)
    assert enu_to_three(10.0, 20.0, 30.0) == (10.0, 30.0, -20.0)
    assert enu_to_sionna(10.0, 20.0, 30.0) == (10.0, 20.0, 30.0)


def test_grid_round_trip_uses_north_to_south_rows():
    frame = SceneFrame(origin_lat=24.0, origin_lon=121.0, origin_alt_m=0.0)
    row, col = enu_to_grid(2.0, 254.0, 0.0, frame)
    assert (row, col) == (0, 64)
    east, north, _ = grid_to_enu(row, col, frame)
    assert (east, north) == (2.0, 254.0)


def test_out_of_extent_is_not_clamped():
    frame = SceneFrame(origin_lat=24.0, origin_lon=121.0, origin_alt_m=0.0)
    result = enu_to_grid(300.0, 0.0, 0.0, frame)
    assert result.inside_extent is False
    assert result.row is None and result.col is None
```

- [ ] **Step 2: Run the new test and verify it fails for the missing module**

Run: `cd backend; .\.venv\Scripts\python -m unittest tests.test_coordinate_frame`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.coordinate_frame'`.

- [ ] **Step 3: Implement the smallest contract**

Implement a frozen `SceneFrame` with `extent=512.0`, `rows=128`, `cols=128`, `display_margin_m=32.0`, plus these functions:

```python
gps_to_enu(lat, lon, alt, frame, alt_mode="amsl") -> tuple[float, float, float]
enu_to_gps(east_m, north_m, up_m, frame, alt_mode="amsl") -> tuple[float, float, float]
enu_to_three(east_m, north_m, up_m) -> tuple[float, float, float]
enu_to_sionna(east_m, north_m, up_m) -> tuple[float, float, float]
enu_to_grid(east_m, north_m, up_m, frame) -> GridPoint
grid_to_enu(row, col, frame) -> tuple[float, float, float]
```

Use the existing local WGS84 meters-per-degree approximation, return `None` grid indices outside the hard extent, and never clamp coordinates.

- [ ] **Step 4: Run the tests and commit the contract**

Run: `cd backend; .\.venv\Scripts\python -m unittest tests.test_coordinate_frame`

Expected: PASS.

Commit: `feat(coords): add backend SceneFrame adapters`.

### Task 2: Mirror the contract in the frontend and add altitude-aware replay primitives

**Files:**
- Create: `frontend/src/types/sceneFrame.ts`
- Modify: `frontend/src/utils/geo.ts`
- Modify: `frontend/tests/geo.test.mjs`
- Modify: `frontend/src/utils/gpsReplay.ts` and its tests if parsing owns `alt_mode`

- [ ] **Step 1: Write failing frontend tests**

```javascript
import { enuToThree, gpsToEnu, threeToEnu } from '../src/utils/geo.ts';

it('maps GPS altitude into ENU up and Three y', () => {
  const frame = { origin: { lat: 24, lon: 121, alt_m: 100 }, alt_mode: 'amsl' };
  const enu = gpsToEnu(24, 121, 125, frame);
  assert.deepEqual(enu, { east_m: 0, north_m: 0, up_m: 25 });
  assert.deepEqual(enuToThree(enu), [0, 25, 0]);
});

it('round-trips Three north as negative z without an xz API', () => {
  const enu = threeToEnu([10, 30, -20]);
  assert.deepEqual(enu, { east_m: 10, north_m: 20, up_m: 30 });
});
```

- [ ] **Step 2: Run the targeted test and verify the new API fails**

Run: `cd frontend; npm test -- --run tests/geo.test.mjs`

Expected: FAIL because `gpsToEnu`, `enuToThree`, and `threeToEnu` are not defined.

- [ ] **Step 3: Implement the frontend adapter**

Define `SceneFrame`, `ENUPoint`, and `GridPoint` types. Replace `latLonToENU` with explicit `gpsToEnu` returning `{east_m,north_m,up_m}`; add `enuToThree` and `threeToEnu`. Keep no `worldXZToLatLon` export. Make `alt_mode="amsl"` subtract `origin.alt_m` and `alt_mode="relative"` use `alt` directly.

- [ ] **Step 4: Run frontend geo and replay tests**

Run: `cd frontend; npm test -- --run tests/geo.test.mjs tests/gps-replay.test.mjs`

Expected: PASS, including a replay point whose `alt` differs from the first point.

- [ ] **Step 5: Commit the frontend adapter**

Commit: `feat(coords): add frontend ENU adapters`.

### Task 3: Make scene generation produce one exact 512m frame

**Files:**
- Modify: `backend/app/blender_generate_scene.py`
- Modify: `backend/app/main.py` generated-scene metadata and response paths
- Modify: `backend/tests/test_generated_scene_index.py`
- Add or modify: generated scene metadata fixture under `backend/tests/fixtures/`

- [ ] **Step 1: Add failing metadata tests**

Extend `test_generated_scene_index.py` with assertions that generated metadata contains:

```python
assert metadata["frame"]["extent"] == {
    "min_e": -256.0, "max_e": 256.0,
    "min_n": -256.0, "max_n": 256.0,
}
assert metadata["frame"]["grid"] == {
    "rows": 128, "cols": 128,
    "pixel_size_e_m": 4.0, "pixel_size_n_m": 4.0,
}
assert metadata["frame"]["display_margin_m"] == 32.0
```

- [ ] **Step 2: Run the scene-index tests and confirm the old metadata fails**

Run: `cd backend; .\.venv\Scripts\python -m unittest tests.test_generated_scene_index`

Expected: FAIL because old generated metadata has `area_m`/bbox information but no `frame` contract.

- [ ] **Step 3: Add frame metadata and fixed asset bounds**

Centralize the 512m extent in `coordinate_frame.py`. Have `blender_generate_scene.py` write the frame into `scene_metadata.json` and use the same extent for source bbox, local asset placement, and export metadata. Reject any generated output whose exported local bounds exceed the frame after clipping. Preserve empty border cells instead of scaling imported geometry to fit.

- [ ] **Step 4: Verify scene generation metadata and commit**

Run: `cd backend; .\.venv\Scripts\python -m unittest tests.test_generated_scene_index`

Expected: PASS.

Commit: `feat(scene): emit fixed Local ENU frame metadata`.

### Task 4: Convert ISS-UNet, routes, CFAR, and Sionna to ENU-only APIs

**Files:**
- Modify: `backend/app/iss_unet_dataset_service.py`
- Modify: `backend/app/iss_real.py`
- Modify: `backend/app/iss_unet_service.py`
- Modify: `backend/app/sionna_service_lite.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_iss_unet_service.py`

- [ ] **Step 1: Update failing response assertions first**

Change one route/CFAR fixture assertion from:

```python
assert point["world_x"] == 2.0
assert point["world_z"] == -2.0
```

to:

```python
assert point["enu"] == {"east_m": 2.0, "north_m": 2.0, "up_m": 0.0}
assert point["grid"]["inside_extent"] is True
```

Add a test that `frame_id` is present and that old metadata without a frame raises the scene validation error.

- [ ] **Step 2: Run the focused backend tests and verify old payloads fail**

Run: `cd backend; .\.venv\Scripts\python -m unittest tests.test_iss_unet_service`

Expected: FAIL on old `world_x/world_z` response fields and legacy bounds fallback.

- [ ] **Step 3: Replace the projection implementation**

Use `coordinate_frame.py` in `_latlon_to_pixel`, `_pixel_to_world`, `_cfar_pixel_to_world`, and route payload construction. Return `enu`, `grid`, `frame_id`, `inside_extent`, and `displayable`. Use fixed `[-256,256]` bounds for every 128×128 grid. Remove `_world_to_latlon` as a public path and replace it with ENU→GPS. Change Sionna request/device payloads to accept ENU tuples and call only `enu_to_sionna`.

- [ ] **Step 4: Update backend tests and run the full backend suite**

Run: `cd backend; .\.venv\Scripts\python -m unittest discover -s tests`

Expected: PASS with no `world_x` or `world_z` assertions remaining.

- [ ] **Step 5: Commit the backend API migration**

Commit: `refactor(coords): migrate backend APIs to ENU`.

### Task 5: Migrate frontend scene, device, replay, and overlays

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/hooks/useGeneratedScene.ts`
- Modify: `frontend/src/types/heatmap.ts`
- Modify: `frontend/src/types/cfar.ts`
- Modify: `frontend/src/components/scene/ISSHeatmapOverlay.tsx`
- Modify: `frontend/src/components/scene/ISSRouteOverlay.tsx`
- Modify: `frontend/src/components/scene/CFARBeaconMarker.tsx`
- Modify: `frontend/src/components/ui/SimulationPanel.tsx`
- Modify: affected frontend tests under `frontend/tests/` and `frontend/src/**/*.test.*`

- [ ] **Step 1: Replace frontend fixtures with ENU payloads**

Change route and CFAR fixtures to use the new shape:

```typescript
{
  lat: 24,
  lon: 121,
  alt: 10,
  enu: { east_m: 2, north_m: 2, up_m: 10 },
  grid: { row: 63, col: 64, inside_extent: true },
  frame_id: 'scene-test'
}
```

Add tests for `displayable=true` when a point is at 270m and `out_of_frame=true` when it is at 300m.

- [ ] **Step 2: Run targeted frontend tests and observe old field failures**

Run: `cd frontend; npm test -- --run tests/iss-route-overlay.test.mjs tests/iss-heatmap-overlay.test.mjs src/components/ui/SimulationPanel.test.tsx`

Expected: FAIL because overlays still read `world_x/world_z`.

- [ ] **Step 3: Convert all rendering inputs at the boundary**

Store the active SceneFrame from generated-scene metadata. Convert GPS/device ENU with `enuToThree`. Make replay call `gpsToEnu` for every point and set Three `y` from that point's `up_m`; remove `SCALE`, `ALT_GAIN`, fixed replay Y, and coordinate use of `Math.max`. Make route and CFAR overlays consume `enu` and derive `[x,y,z]` through `enuToThree`; keep `displayable` filtering without clamping. Make heatmap planes derive position from the fixed frame/grid metadata.

- [ ] **Step 4: Run frontend tests and build**

Run: `cd frontend; npm test`

Expected: PASS with no tests or source references to `world_x`, `world_z`, `VITE_SCENE_SCALE`, or `ALT_GAIN` in coordinate code.

Run: `cd frontend; npm run build`

Expected: exit code 0.

- [ ] **Step 5: Commit the frontend migration**

Commit: `refactor(coords): render all local positions from ENU`.

### Task 6: Make GPS sources explicit about altitude mode

**Files:**
- Modify: `tools/ap3_to_gps_csv.py`
- Modify: `tools/ap3_to_simulator.py`
- Modify: `backend/app/iss_real.py` GPS parser and route alignment
- Modify: frontend GPS replay parser/types
- Modify: `backend/tests/` and `frontend/tests/gps-replay.test.mjs`

- [ ] **Step 1: Add failing parser tests**

```python
def test_gps_csv_preserves_alt_mode():
    points = parse_gps_csv("time_stamp,lat,lon,alt,alt_mode\n"
                           "2026-01-01T00:00:00,24,121,25,amsl\n")
    assert points[0].alt_mode == "amsl"
```

- [ ] **Step 2: Run the parser tests and confirm `alt_mode` is missing**

Run: `cd backend; .\.venv\Scripts\python -m unittest tests.test_iss_unet_service`

Expected: FAIL because the parser does not expose `alt_mode`.

- [ ] **Step 3: Add explicit source metadata**

Write `alt_mode` into AP3 CSV headers/rows and include it in the WebSocket payload. Keep the CLI choices `relative` and `amsl`. For legacy CSV rows without the column, set `alt_mode="relative"` and `legacy_alt_mode=true` so replay uses the confirmed compatibility rule.

- [ ] **Step 4: Run parser, replay, backend, and frontend checks**

Run: `cd backend; .\.venv\Scripts\python -m unittest discover -s tests`

Run: `cd frontend; npm test -- --run tests/gps-replay.test.mjs tests/geo.test.mjs`

Expected: PASS.

- [ ] **Step 5: Commit the altitude-mode change**

Commit: `feat(gps): preserve altitude mode in replay data`.

### Task 7: Regenerate compatible NTPU/NYCU assets and verify end to end

**Files:**
- Modify generated tracked assets under `backend/app/static/scenes/NTPU/` and `backend/app/static/scenes/NYCU/`.
- Modify `frontend/public/scenes/NTPU.glb` and `frontend/public/scenes/NYCU.glb` only after the new generator succeeds.
- Do not modify `backup/legacy-scenes-20260712`.

- [ ] **Step 1: Verify the backup reference**

Run: `git show --stat --oneline backup/legacy-scenes-20260712`

Expected: the tag points to the pre-migration commit containing the original NTPU/NYCU assets.

- [ ] **Step 2: Generate NTPU with the new frame**

Run from `backend` with the existing NTPU center:

```powershell
.\.venv\Scripts\python app\blender_generate_scene.py `
  --lat 24.943476 --lon 121.370054 --zoom 16 --area-m 512 `
  --scene-name NTPU --scene-key NTPU `
  --output-dir app\static\scenes\NTPU --basemap-style satellite
```

Expected: the output contains GLB/PLY/XML and metadata with `frame.extent` exactly `[-256,256]` on E/N and no actual-bounds expansion.

- [ ] **Step 3: Generate NYCU with the new frame**

Run:

```powershell
.\.venv\Scripts\python app\blender_generate_scene.py `
  --lat 24.967052 --lon 121.536335 --zoom 16 --area-m 512 `
  --scene-name NYCU --scene-key NYCU `
  --output-dir app\static\scenes\NYCU --basemap-style satellite
```

Expected: the output contains the same frame schema and fixed bounds.

- [ ] **Step 4: Rebuild ISS-UNet artifacts against each new scene**

Run the existing dataset preparation path with `scene=NTPU`, `scene=NYCU`, `grid_res=128`, and `area_m=512`. Verify `scene_meta.json`, building height, and Sionna arrays all reference the same `frame_id`, bounds, and 4m pixel size.

- [ ] **Step 5: Run final verification**

Run: `cd backend; .\.venv\Scripts\python -m unittest discover -s tests`

Run: `cd frontend; npm test`

Run: `cd frontend; npm run build`

Run: `git grep -n -E 'world_x|world_z' -- ':!docs/superpowers/specs' ':!docs/superpowers/plans'`

Expected: all tests/build pass; the final grep returns no source/API references.

- [ ] **Step 6: Commit regenerated assets and migration**

Commit: `feat(coords): regenerate fixed-frame NTPU and NYCU scenes`.

## Plan self-review

- Spec coverage: SceneFrame, fixed 512m extent, 32m display margin, altitude-aware replay, ENU-only APIs, removal of `world_x/world_z`, scene regeneration, and backup verification each have an explicit task.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation step is used.
- Type consistency: backend uses `SceneFrame`/`GridPoint`; frontend uses `SceneFrame`/`ENUPoint`; API fields are consistently `frame_id`, `enu`, and `grid`.
- Verification coverage: every production change starts with a failing test, and the final backend suite, frontend suite, build, and source grep are specified.
