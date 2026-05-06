# CFR Advanced Parameters Panel Design

## Goal

Add a collapsed advanced settings section to the CFR tab in the wireless
simulation panel. The section lets users tune key CFR and constellation
simulation controls without exposing raw implementation variable names in the
UI.

## Approved UI Direction

Use a collapsed "進階設定" block under the existing CFR modulation selector.
The CFR tab keeps the current simple default view:

- 調變方式
- 進階設定 toggle
- 開始計算

When expanded, the advanced block shows five rows. Each row contains a
domain-facing label, a compact control, a red/yellow/green compute-impact
badge, and one short explanation sentence.

## Parameter Rows

| UI label | Default | Control | Impact badge | Help text |
| --- | ---: | --- | --- | --- |
| Constellation Batch Size | 1 | Select: 1, 10, 50, 100 | Yellow / 中 | 控制星座圖的獨立樣本組數。 |
| OFDM Subcarriers | 76 | Select: 76, 128, 256, 512 | Red / 高 | 控制 CFR 頻域取樣點數。 |
| Subcarrier Spacing | 30 kHz | Number input, step 15 kHz | Green / 低 | 控制相鄰子載波的頻率間隔。 |
| Eb/N0 | 20 dB | Number input, step 1 dB | Green / 低 | 控制訊號相對背景雜訊的品質。 |
| Ray Tracing Max Depth | 10 | Select: 1, 3, 5, 10 | Red / 高 | 控制多路徑追蹤的最大互動深度。 |

The UI must not display the raw backend variable names. It may use the labels
above because they are standard communication and channel-modeling terms.

## Frontend Design

`SimulationPanel.tsx` will add CFR-specific advanced state next to the existing
`cfrModulation` state.

The CFR section will render:

- Existing modulation selector.
- A compact "進階設定" toggle.
- The advanced rows only when expanded.

The current inline style pattern can remain for this scoped change. To keep the
file readable, the advanced CFR rows should use small helper components, such
as `ImpactBadge`, `HelpText`, and a parameter row wrapper.

Impact badge colors:

- Green / 低: low compute impact.
- Yellow / 中: medium compute impact.
- Red / 高: high compute impact.

## Request Payload Design

The CFR POST request will include an optional nested advanced parameter object.
The frontend sends it only for CFR requests.

Example shape:

```json
{
  "scene": "NTPU",
  "modulation": "qpsk",
  "devices": [],
  "advanced": {
    "constellation_batch_size": 1,
    "ofdm_subcarriers": 76,
    "subcarrier_spacing_hz": 30000,
    "ebn0_db": 20,
    "ray_tracing_max_depth": 10
  }
}
```

The field names can be technical in the API because they are not user-facing.

## Backend Design

`main.py` will extend `CFRPlotRequest` with an optional advanced parameter
model. Validation should keep values bounded before they reach Sionna:

- `constellation_batch_size`: 1 to 100.
- `ofdm_subcarriers`: 16 to 1024.
- `subcarrier_spacing_hz`: 1000 to 240000.
- `ebn0_db`: 0 to 60.
- `ray_tracing_max_depth`: 1 to 10.

`generate_cfr_plot()` will accept matching optional arguments with current
defaults. Existing callers without advanced parameters keep the current
behavior.

The constellation bit tensor will use the selected batch size, so plotted point
count scales with `batch size * subcarriers`. Frequency generation will use the
selected subcarrier count and spacing. The path solver will use the selected
max depth. Noise variance will use the selected Eb/N0 value.

## Error Handling

Invalid advanced parameter values should return a 422 response from FastAPI
validation when possible. Runtime Sionna failures keep the existing error
handling path.

The frontend should surface the returned error in the existing CFR error box.
No new error UI is needed.

## Testing

Verification should include:

- Frontend build/type check.
- Backend syntax/import check where available.
- CFR request payload inspection through code review or a targeted test.
- Manual UI check that the advanced section is collapsed by default and sends
  selected values when expanded or changed.

## Out of Scope

This design does not add controls for antenna array shape, antenna pattern,
polarization, time snapshots, or delay normalization. Those can be handled in a
separate change if needed.
