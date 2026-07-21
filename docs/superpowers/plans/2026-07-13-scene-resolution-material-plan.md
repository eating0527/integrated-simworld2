# 場景解析度與材質修復 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every new scene produce 1m/2m/4m ISS-UNet datasets and regenerate textured NTPU/NYCU scenes.

**Architecture:** Keep the existing scene-task coordinator and dataset service. The coordinator calls the existing `prepare_iss_unet_dataset` once per supported pixel size and exposes the 4m result at the existing top level with all results nested under `resolutions`. Resolve Blender output paths before any image/material load so basemap textures and GLB packaging use absolute paths.

**Tech Stack:** Python 3.11, unittest, Blender 3.6, Sionna RT, NumPy, React/Vite assets.

---

### Task 1: Add the failing multi-resolution coordinator test

**Files:**
- Modify: `backend/tests/test_generated_scene_index.py`

- [ ] **Step 1: Add a test that records all requested pixel sizes**

Add this test beside the existing completed-scene dataset tests:

```python
    def test_completed_scene_task_prepares_all_iss_unet_resolutions(self):
        task = _task("task-ok", "T-AAAAAAAAAA", status="running")
        task["outputDir"] = str(self.scene_dir / "T-AAAAAAAAAA")
        self._write_tasks([task])
        _write_scene(self.scene_dir, "T-AAAAAAAAAA")

        prepare_calls = []

        def fake_prepare(scene, scene_dir, pixel_size_m):
            prepare_calls.append((scene, scene_dir, pixel_size_m))
            return {"available": True, "pixel_size_m": pixel_size_m}

        with patch.object(main, "_run_blender_task_sync", return_value={
            "success": True,
            "outputDir": str(self.scene_dir / "T-AAAAAAAAAA"),
            "sceneKey": "T-AAAAAAAAAA",
            "modelUrl": "/generated-scenes/T-AAAAAAAAAA/T-AAAAAAAAAA.glb",
            "sionnaSceneXml": str(self.scene_dir / "T-AAAAAAAAAA" / "T-AAAAAAAAAA.xml"),
        }):
            with patch("app.iss_unet_dataset_service.prepare_iss_unet_dataset", side_effect=fake_prepare):
                asyncio.run(main._process_scene_task("task-ok"))

        updated = json.loads(self.tasks_json.read_text(encoding="utf-8"))[0]
        self.assertEqual([call[2] for call in prepare_calls], [1, 2, 4])
        datasets = updated["issUnetDataset"]["resolutions"]
        self.assertEqual(sorted(datasets), ["1m", "2m", "4m"])
        self.assertEqual(updated["issUnetDataset"]["pixel_size_m"], 4)
```

- [ ] **Step 2: Run the focused test and confirm the expected failure**

Run from `backend`:

```powershell
.\.venv\Scripts\python -m unittest tests.test_generated_scene_index.GeneratedSceneIndexTests.test_completed_scene_task_prepares_all_iss_unet_resolutions
```

Expected: FAIL because the current coordinator calls the service once without `pixel_size_m` and does not return `resolutions`.

### Task 2: Implement multi-resolution preparation

**Files:**
- Modify: `backend/app/main.py:1096-1115`
- Modify: `backend/tests/test_generated_scene_index.py` (update the existing single-call test for the new service signature)

- [ ] **Step 1: Update the existing fake service call signature**

Change the existing `fake_prepare` in `test_completed_scene_task_prepares_iss_unet_dataset` to accept `pixel_size_m`, record it, and assert the 4m-compatible top-level result plus the `1m/2m/4m` calls.

- [ ] **Step 2: Add the minimal coordinator loop**

Replace the single service call with:

```python
    pixel_sizes = (1, 2, 4)
    prepared = {
        f"{pixel_size_m}m": prepare_iss_unet_dataset(
            scene_key,
            scene_dir=SCENE_DIR,
            pixel_size_m=pixel_size_m,
        )
        for pixel_size_m in pixel_sizes
    }
    default_result = prepared["4m"]
    return {
        "stage": "iss_unet_dataset_prepared",
        "note": "Blender stage completed and ISS_UNET datasets prepared",
        "issUnetDataset": {**default_result, "resolutions": prepared},
    }
```

Keep the current exception boundary so a failed resolution reports `iss_unet_dataset_failed` and does not falsely report preparation success.

- [ ] **Step 3: Run the focused scene tests**

Run:

```powershell
.\.venv\Scripts\python -m unittest tests.test_generated_scene_index
```

Expected: PASS, including both the new resolution test and existing scene-task tests.

### Task 3: Add and implement absolute Blender output paths

**Files:**
- Modify: `backend/app/blender_generate_scene.py:304-320`
- Modify: `backend/tests/test_generated_scene_index.py`

- [ ] **Step 1: Add the failing path-resolution test**

Add:

```python
    def test_blender_output_dir_is_resolved_before_asset_generation(self):
        relative_dir = Path(".test_tmp") / "relative-scene"
        self.assertEqual(
            blender_generate_scene.resolve_output_dir(relative_dir),
            relative_dir.resolve(),
        )
```

Run the single test and confirm it fails because `resolve_output_dir` does not exist.

- [ ] **Step 2: Add the one-line path helper and use it**

Near the other generator helpers add:

```python
def resolve_output_dir(output_dir: str | Path) -> Path:
    return Path(output_dir).expanduser().resolve()
```

In `main()` change:

```python
    out_dir = resolve_output_dir(args.output_dir)
```

This makes the existing basemap image load, blend save, PLY export, XML export, and GLB export use the same absolute directory without changing the material pipeline.

- [ ] **Step 3: Run the focused generator tests**

Run:

```powershell
.\.venv\Scripts\python -m unittest tests.test_generated_scene_index
```

Expected: PASS.

### Task 4: Regenerate NTPU and NYCU assets

**Files:**
- Regenerate: `backend/app/static/scenes/NTPU/`
- Regenerate: `backend/app/static/scenes/NYCU/`
- Sync generated GLB: `frontend/public/scenes/NTPU.glb`, `frontend/public/scenes/NYCU.glb`

- [ ] **Step 1: Generate NTPU with the existing center**

From `backend` run:

```powershell
& "C:\Program Files\Blender Foundation\Blender 3.6\blender.exe" --background --python app\blender_generate_scene.py -- --lat 24.943476 --lon 121.370054 --zoom 18 --area-m 512 --scene-name NTPU --scene-key NTPU --output-dir "$PWD\app\static\scenes\NTPU" --basemap-style satellite
```

Expected: exit code 0, `scene_metadata.json` has `status=completed`, `basemap_added=true`, and `osm_basemap_bbox_18.png` exists.

- [ ] **Step 2: Generate NYCU with the existing center**

From `backend` run:

```powershell
& "C:\Program Files\Blender Foundation\Blender 3.6\blender.exe" --background --python app\blender_generate_scene.py -- --lat 24.967052 --lon 121.536335 --zoom 18 --area-m 512 --scene-name NYCU --scene-key NYCU --output-dir "$PWD\app\static\scenes\NYCU" --basemap-style satellite
```

Expected: same metadata and basemap checks as NTPU.

- [ ] **Step 3: Prepare all datasets for both regenerated scenes**

From `backend` run this existing service three times per scene through the venv Python:

```powershell
@('NTPU','NYCU') | ForEach-Object {
    $scene = $_
    @('1','2','4') | ForEach-Object {
        $pixel = [int]$_
        .\.venv\Scripts\python -c "from app.iss_unet_dataset_service import prepare_iss_unet_dataset; print(prepare_iss_unet_dataset('$scene', pixel_size_m=$pixel)['meta']['pixel_size_m'])"
    }
}
```

Expected: each scene has `building_height_512.npy`, `building_height_256.npy`, `building_height_128.npy`, and matching DSS/ISS/TSS files; each run prints its requested pixel size.

- [ ] **Step 4: Copy the regenerated GLBs to the frontend public assets**

Run from repository root:

```powershell
Copy-Item -LiteralPath backend\app\static\scenes\NTPU\NTPU.glb -Destination frontend\public\scenes\NTPU.glb -Force
Copy-Item -LiteralPath backend\app\static\scenes\NYCU\NYCU.glb -Destination frontend\public\scenes\NYCU.glb -Force
```

### Task 5: Full verification and handoff

**Files:**
- Verify only; no new source files.

- [ ] **Step 1: Run the backend tests**

```powershell
cd backend
.\.venv\Scripts\python -m unittest discover -s tests
```

Expected: exit code 0 with no test failures.

- [ ] **Step 2: Run frontend tests and build**

```powershell
cd frontend
npm test -- --run
npm run build
```

Expected: both commands exit 0.

- [ ] **Step 3: Verify generated artifacts**

Check both scene directories with a short PowerShell assertion:

```powershell
cd ..
@('NTPU','NYCU') | ForEach-Object {
    $dir = Join-Path "backend\app\static\scenes" $_
    $meta = Get-Content (Join-Path $dir "scene_metadata.json") | ConvertFrom-Json
    if ($meta.status -ne 'completed' -or -not $meta.basemap_added) { throw "$_ scene metadata invalid" }
    if (-not (Test-Path (Join-Path $dir "osm_basemap_bbox_18.png"))) { throw "$_ basemap missing" }
    foreach ($grid in 128,256,512) {
        $suffix = if ($grid -eq 128) { '' } else { "_$grid" }
        foreach ($file in "building_height_$grid.npy", "sionna_dss$suffix.npy", "sionna_iss$suffix.npy", "sionna_tss$suffix.npy") {
            if (-not (Test-Path (Join-Path $dir "iss_unet_data\$file"))) { throw "$_ missing $file" }
        }
    }
}
```

- [ ] **Step 4: Inspect the final diff and status**

Run:

```powershell
git status --short
git diff --stat
git diff --check
```

Confirm only the planned source/tests/spec/plan and regenerated NTPU/NYCU assets changed; retain unrelated pre-existing user changes untouched.
