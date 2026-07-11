# Restore Generated Scene Support for Advanced Sionna Simulations

**Goal:** Enable SINR Map, Doppler, and Channel IR simulations for custom generated scenes by updating `sionna_service.py` to accept dynamic scene XMLs and updating `main.py` and the frontend to support these operations.

**Architecture:** 
Update `sionna_service.py` simulation functions to accept a `scene_xml` parameter (defaulting to NYCU for backwards compatibility). Add new POST endpoints in `main.py` that accept the scene identifier and device configurations. Update the React frontend to remove restrictions on these tabs for generated scenes and use the new POST endpoints.

**Tech Stack:** Python (FastAPI, Sionna), React (TypeScript).

---

### Task 0: Project Documentation & Gitignore

**Files:**
- Create: `docs/plans/generated-scene-sionna-support.md`
- Modify: `.gitignore`

- [ ] **Step 1: Create the plans directory and save the plan**
- [ ] **Step 2: Update `.gitignore` to exclude the plans directory**

```text
# Add to .gitignore
docs/plans/
```

### Task 1: Update `sionna_service.py` to accept `scene_xml`

**Files:**
- Modify: `backend/app/sionna_service.py`

- [ ] **Step 1: Update `generate_sinr_map` signature and logic**

Modify the signature and the `scene_xml` assignment in `backend/app/sionna_service.py`:

```python
async def generate_sinr_map(
    output_path: str = SINR_MAP_PATH,
    tx_list: Optional[List[Tuple]] = None,
    rx_config: Optional[Tuple] = None,
    sinr_vmin: float = -40.0,
    sinr_vmax: float = 0.0,
    cell_size: float = 1.0,
    samples_per_tx: int = 10 ** 7,
    scene_xml: Optional[str] = None,
) -> bool:
# ... inside try block ...
        if scene_xml is None:
            scene_xml = str(NYCU_XML)
        logger.info(f"使用場景: {scene_xml}")

        scene = _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                             tx_list, rx_config, scene_xml)
```

- [ ] **Step 2: Update `generate_doppler_plot` signature and logic**

Modify the signature and the `_build_scene` call in `backend/app/sionna_service.py`:

```python
async def generate_doppler_plot(
    output_path: str = DOPPLER_PLOT_PATH,
    tx_list: Optional[List[Tuple]] = None,
    rx_config: Optional[Tuple] = None,
    scene_xml: Optional[str] = None,
) -> bool:
# ... inside try block ...
        if scene_xml is None:
            scene_xml = str(NYCU_XML)
            
        scene = _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                             tx_list, rx_config, scene_xml)
```

- [ ] **Step 3: Update `generate_channel_response` signature and logic**

Modify the signature and the `_build_scene` call in `backend/app/sionna_service.py`:

```python
async def generate_channel_response(
    output_path: str = CHANNEL_RESP_PATH,
    tx_list: Optional[List[Tuple]] = None,
    rx_config: Optional[Tuple] = None,
    scene_xml: Optional[str] = None,
) -> bool:
# ... inside try block ...
        if scene_xml is None:
            scene_xml = str(NYCU_XML)
            
        scene = _build_scene(load_scene, SionnaTX, SionnaRX, PlanarArray,
                             tx_list, rx_config, scene_xml)
```

### Task 2: Update `main.py` with new POST endpoints

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Define request models**

Add these models near the other Sionna models (e.g., above `CFRPlotRequest`):

```python
class BaseSionnaRequest(BaseModel):
    scene: str
    devices: List[DeviceIn]

class SINRMapRequest(BaseSionnaRequest):
    sinr_vmin: float = Field(default=-20.0)
    sinr_vmax: float = Field(default=40.0)
    cell_size: float = Field(default=2.0)
    samples_per_tx: int = Field(default=100000000)
```

- [ ] **Step 2: Add POST endpoint for SINR Map**

Add this below the existing GET endpoints:

```python
@app.post("/api/sionna/sinr-map")
async def sionna_sinr_map_post(req: SINRMapRequest):
    try:
        from app.sionna_service import generate_sinr_map, SINR_MAP_PATH

        scene_xml = _resolve_sionna_scene_xml(req.scene)
        tx_list, rx_config = _cfr_device_config(req.devices) # reuse device config logic
        
        await generate_sinr_map(
            tx_list=tx_list,
            rx_config=rx_config,
            scene_xml=str(scene_xml),
            sinr_vmin=req.sinr_vmin,
            sinr_vmax=req.sinr_vmax,
            cell_size=req.cell_size,
            samples_per_tx=req.samples_per_tx,
        )
        if not os.path.isfile(SINR_MAP_PATH):
            return JSONResponse({"error": "圖檔生成失敗，請查看後端 log"}, status_code=500)
        return FileResponse(SINR_MAP_PATH, media_type="image/png", filename="sinr_map.png")
    except HTTPException:
        raise
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("sinr-map", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.exception("SINR map error")
        return JSONResponse({"error": str(e)}, status_code=500)
```

- [ ] **Step 3: Add POST endpoint for Doppler Plot**

```python
@app.post("/api/sionna/doppler")
async def sionna_doppler_post(req: BaseSionnaRequest):
    try:
        from app.sionna_service import generate_doppler_plot, DOPPLER_PLOT_PATH

        scene_xml = _resolve_sionna_scene_xml(req.scene)
        tx_list, rx_config = _cfr_device_config(req.devices)
        
        await generate_doppler_plot(
            tx_list=tx_list,
            rx_config=rx_config,
            scene_xml=str(scene_xml),
        )
        if not os.path.isfile(DOPPLER_PLOT_PATH):
            return JSONResponse({"error": "圖檔生成失敗，請查看後端 log"}, status_code=500)
        return FileResponse(DOPPLER_PLOT_PATH, media_type="image/png", filename="doppler_plot.png")
    except HTTPException:
        raise
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("doppler", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.exception("Doppler plot error")
        return JSONResponse({"error": str(e)}, status_code=500)
```

- [ ] **Step 4: Add POST endpoint for Channel Response**

```python
@app.post("/api/sionna/channel-response")
async def sionna_channel_response_post(req: BaseSionnaRequest):
    try:
        from app.sionna_service import generate_channel_response, CHANNEL_RESP_PATH

        scene_xml = _resolve_sionna_scene_xml(req.scene)
        tx_list, rx_config = _cfr_device_config(req.devices)
        
        await generate_channel_response(
            tx_list=tx_list,
            rx_config=rx_config,
            scene_xml=str(scene_xml),
        )
        if not os.path.isfile(CHANNEL_RESP_PATH):
            return JSONResponse({"error": "圖檔生成失敗，請查看後端 log"}, status_code=500)
        return FileResponse(CHANNEL_RESP_PATH, media_type="image/png", filename="channel_response.png")
    except HTTPException:
        raise
    except SionnaLLVMError as e:
        return _sionna_llvm_error_response("channel-response", e)
    except ImportError:
        return JSONResponse({"error": "Sionna 未安裝，請先執行 pip install sionna"}, status_code=503)
    except Exception as e:
        logger.exception("Channel response error")
        return JSONResponse({"error": str(e)}, status_code=500)
```

### Task 3: Update Frontend `SimulationPanel.tsx`

**Files:**
- Modify: `frontend/src/components/ui/SimulationPanel.tsx`

- [ ] **Step 1: Unlock tabs for generated scenes**

Change `GENERATED_SCENE_TABS` to include all tabs:

```typescript
const GENERATED_SCENE_TABS: TabKey[] = ['sinr', 'cfr', 'doppler', 'channel', 'iss', 'tss', 'cfar'];
```

- [ ] **Step 2: Update `compute` function to use POST endpoints for all tools**

Update the `compute` logic to use POST for `sinr`, `doppler`, and `channel` (like `cfr` does).

```typescript
// Replace the `if (key === 'cfr') { ... } else if (['iss', 'tss', 'cfar'].includes(key)) { ... } else { ... }` block with:

      let res;
      const requestSceneId = sceneId ?? 'NTPU';
      const devicePayload = devices.map(d => ({
        name: d.name,
        role: d.role,
        x: d.x,
        y: d.y,
        z: d.z,
        power_dbm: d.powerDbm ?? null,
      }));

      if (key === 'cfr') {
        res = await fetch(`${API}/api/sionna/cfr-plot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scene: requestSceneId,
            modulation: cfrModulation,
            advanced: {
              constellation_batch_size: cfrAdvanced.constellationBatchSize,
              ofdm_subcarriers: cfrAdvanced.ofdmSubcarriers,
              subcarrier_spacing_hz: cfrAdvanced.subcarrierSpacingHz,
              ebn0_db: cfrAdvanced.ebn0Db,
              ray_tracing_max_depth: cfrAdvanced.rayTracingMaxDepth,
            },
            devices: devicePayload,
          }),
        });
      } else if (['iss', 'tss', 'cfar'].includes(key)) {
        res = await fetch(`${API}/api/simulate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scene: requestSceneId,
            map_type: key,
            cell_size: sinrParams.cell_size,
            samples_per_tx: sinrParams.samples_per_tx,
            overlay_scene: overlayScene,
            devices: devicePayload,
          }),
        });
      } else if (key === 'sinr') {
         res = await fetch(`${API}/api/sionna/sinr-map`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scene: requestSceneId,
            sinr_vmin: sinrParams.sinr_vmin,
            sinr_vmax: sinrParams.sinr_vmax,
            cell_size: sinrParams.cell_size,
            samples_per_tx: sinrParams.samples_per_tx,
            devices: devicePayload,
          }),
        });
      } else if (key === 'doppler') {
        res = await fetch(`${API}/api/sionna/doppler`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scene: requestSceneId,
            devices: devicePayload,
          }),
        });
      } else if (key === 'channel') {
        res = await fetch(`${API}/api/sionna/channel-response`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scene: requestSceneId,
            devices: devicePayload,
          }),
        });
      }
```

- [ ] **Step 3: Remove `buildSinrUrl` (optional cleanup)**

Since `buildSinrUrl` is no longer used, remove it from the file.

```typescript
// Remove this function entirely
// function buildSinrUrl(params: SINRParams): string { ... }
```
