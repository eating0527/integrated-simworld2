# Device Coordinate Mode Implementation Plan

> Status: completed 2026-07-13. This plan records the delivered scope and verification.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use Markdown checkboxes for tracking.

**Goal:** 在裝置設定面板加入全域 GPS/xyz 座標切換，讓 TX、RX、Jammer 以目前 scene frame 內的位置草稿套用，且切換不產生座標失同步。

**Architecture:** `Device.x/y/z` 維持唯一 canonical 位置；面板依 `coordMode` 用既有 `geo.ts` 轉換顯示與套用。每列座標只保留本地文字草稿，切換模式、scene frame 或 canonical 位置變更時重新由已套用 xyz 產生草稿，並以 `enuToGrid(...).inside_extent` 驗證 scene 範圍。

**Tech Stack:** React 19, TypeScript, Zustand, Vitest, Testing Library, Sass。

---

## 檔案地圖

- Modify: `frontend/src/components/ui/DevicePanel.tsx` — 全域模式、原生 SVG icon、GPS/xyz 欄位、草稿、套用與 extent 驗證。
- Modify: `frontend/src/App.tsx:500` — 將 `activeFrame` 傳給 `DevicePanel`。
- Modify: `frontend/src/styles/main.scss:362-574` — 單欄座標版面、工具列、icon button、錯誤與 focus 樣式。
- Create: `frontend/src/components/ui/DevicePanel.test.tsx` — UI、轉換、驗證、草稿與無障礙回歸測試。
- Reuse without changes: `frontend/src/utils/geo.ts`, `frontend/src/types/sceneFrame.ts`, `frontend/src/types/device.ts`, `frontend/src/store/useDeviceStore.ts`。

## Task 1: 建立失敗中的面板行為測試

**Files:**
- Create: `frontend/src/components/ui/DevicePanel.test.tsx`

- [x] **Step 1: 建立測試資料、render helper 與 store reset**

```tsx
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DevicePanel } from './DevicePanel';
import { useDeviceStore } from '../../store/useDeviceStore';
import { createSceneFrame } from '../../types/sceneFrame';
import { enuToGps, enuToThree, gpsToEnu, threeToEnu } from '../../utils/geo';

const frame = createSceneFrame('scene-test', { lat: 24, lon: 121, alt_m: 100 });

const devices = [
  { id: 'dev-tx-0', name: 'tx-0', role: 'tx' as const, x: -75, y: 0, z: 75, powerDbm: 60 },
  { id: 'dev-rx-0', name: 'rx-0', role: 'rx' as const, x: -30, y: 10, z: 175 },
  { id: 'dev-jam-0', name: 'jam-0', role: 'jammer' as const, x: -150, y: 0, z: 170, powerDbm: 60 },
];

function renderOpenPanel(onApplyRxPosition = vi.fn()) {
  const view = render(
    <DevicePanel sceneFrame={frame} onApplyRxPosition={onApplyRxPosition} />,
  );
  userEvent.setup();
  return view;
}

async function openPanel() {
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: /restore 裝置設定/i }));
  return user;
}

beforeEach(() => {
  useDeviceStore.setState({ devices });
});
```

The helper must pass the new required `sceneFrame` prop and keep the three canonical device ids used by `App` and the existing store defaults.

- [x] **Step 2: 加入 GPS 套用、三角色與 RX 同步測試**

```tsx
it('applies GPS positions for TX, RX, and Jammer inside the active scene', async () => {
  renderOpenPanel();
  const user = await openPanel();

  const expectedGps = { lat: 24.001, lon: 121.001, alt: 110 };
  const txRow = screen.getByDisplayValue('tx-0').closest('.dp-device-row')!;
  await user.clear(within(txRow).getByRole('textbox', { name: '緯度 tx-0' }));
  await user.type(within(txRow).getByRole('textbox', { name: '緯度 tx-0' }), String(expectedGps.lat));
  await user.clear(within(txRow).getByRole('textbox', { name: '經度 tx-0' }));
  await user.type(within(txRow).getByRole('textbox', { name: '經度 tx-0' }), String(expectedGps.lon));
  await user.clear(within(txRow).getByRole('textbox', { name: '高度 tx-0' }));
  await user.type(within(txRow).getByRole('textbox', { name: '高度 tx-0' }), String(expectedGps.alt));
  await user.click(within(txRow).getByRole('button', { name: '套用位置' }));

  const expected = enuToThree(gpsToEnu(expectedGps, frame, frame.alt_mode));
  expect(useDeviceStore.getState().devices.find((device) => device.id === 'dev-tx-0')).toMatchObject({
    x: expected[0], y: expected[1], z: expected[2],
  });
  expect(screen.getAllByRole('button', { name: '套用位置' })).toHaveLength(3);
});

it('notifies App when the RX position is applied', async () => {
  const onApplyRxPosition = vi.fn();
  renderOpenPanel(onApplyRxPosition);
  const user = await openPanel();
  const rxRow = screen.getByDisplayValue('rx-0').closest('.dp-device-row')!;

  await user.click(within(rxRow).getByRole('button', { name: '套用位置' }));

  const rx = useDeviceStore.getState().devices.find((device) => device.id === 'dev-rx-0')!;
  expect(onApplyRxPosition).toHaveBeenCalledWith([rx.x, rx.y, rx.z]);
});
```

- [x] **Step 3: 加入切換、草稿捨棄與無漂移測試**

```tsx
it('discards an unsubmitted draft when switching modes', async () => {
  renderOpenPanel();
  const user = await openPanel();
  const txRow = screen.getByDisplayValue('tx-0').closest('.dp-device-row')!;
  const toggle = screen.getByRole('button', { name: '切換為 XYZ 座標' });

  await user.clear(within(txRow).getByRole('textbox', { name: '緯度 tx-0' }));
  await user.type(within(txRow).getByRole('textbox', { name: '緯度 tx-0' }), '24.1');
  await user.click(toggle);

  expect(within(txRow).getByRole('textbox', { name: 'X tx-0' })).toHaveValue('-75');
  expect(within(txRow).getByRole('textbox', { name: 'Y tx-0' })).toHaveValue('0');
  expect(within(txRow).getByRole('textbox', { name: 'Z tx-0' })).toHaveValue('75');
});

it('rebinds GPS and xyz to the same committed position', async () => {
  renderOpenPanel();
  const user = await openPanel();
  const txRow = screen.getByDisplayValue('tx-0').closest('.dp-device-row')!;
  const toggle = screen.getByRole('button', { name: '切換為 XYZ 座標' });
  const device = useDeviceStore.getState().devices.find((item) => item.id === 'dev-tx-0')!;
  const expectedGps = enuToGps(threeToEnu([device.x, device.y, device.z]), frame, frame.alt_mode);

  await user.click(toggle);
  await user.click(screen.getByRole('button', { name: '切換為 GPS 經緯度' }));

  expect(within(txRow).getByRole('textbox', { name: '緯度 tx-0' })).toHaveValue(String(expectedGps.lat));
  expect(within(txRow).getByRole('textbox', { name: '經度 tx-0' })).toHaveValue(String(expectedGps.lon));
  expect(within(txRow).getByRole('textbox', { name: '高度 tx-0' })).toHaveValue(String(expectedGps.alt));
});
```

- [x] **Step 4: 加入輸入驗證、scene extent 與 ARIA 測試**

```tsx
it('rejects incomplete and out-of-range GPS values without updating the store', async () => {
  renderOpenPanel();
  const user = await openPanel();
  const txRow = screen.getByDisplayValue('tx-0').closest('.dp-device-row')!;
  const before = useDeviceStore.getState().devices.find((item) => item.id === 'dev-tx-0')!;
  const latitude = within(txRow).getByRole('textbox', { name: '緯度 tx-0' });

  await user.clear(latitude);
  expect(within(txRow).getByRole('button', { name: '套用位置' })).toBeDisabled();
  expect(useDeviceStore.getState().devices.find((item) => item.id === 'dev-tx-0')).toEqual(before);

  await user.type(latitude, '24.003');
  expect(within(txRow).getByText('超出目前場景範圍')).toBeInTheDocument();
  expect(useDeviceStore.getState().devices.find((item) => item.id === 'dev-tx-0')).toEqual(before);
});

it('allows a position inside the extent and rejects the exclusive max boundary', async () => {
  renderOpenPanel();
  const user = await openPanel();
  const txRow = screen.getByDisplayValue('tx-0').closest('.dp-device-row')!;
  const toggle = screen.getByRole('button', { name: '切換為 XYZ 座標' });
  await user.click(toggle);
  const x = within(txRow).getByRole('textbox', { name: 'X tx-0' });

  await user.clear(x);
  await user.type(x, '255.9');
  await user.click(within(txRow).getByRole('button', { name: '套用位置' }));
  expect(useDeviceStore.getState().devices.find((item) => item.id === 'dev-tx-0')?.x).toBe(255.9);

  await user.clear(x);
  await user.type(x, '256');
  expect(within(txRow).getByText('超出目前場景範圍')).toBeInTheDocument();
});

it('exposes the global coordinate toggle to assistive technology', async () => {
  renderOpenPanel();
  await openPanel();
  const toggle = screen.getByRole('button', { name: '切換為 XYZ 座標' });
  expect(toggle).toHaveAttribute('aria-pressed', 'true');
  expect(toggle).toHaveAttribute('aria-controls');
  await userEvent.setup().click(toggle);
  expect(toggle).toHaveAttribute('aria-pressed', 'false');
});
```

- [x] **Step 5: 執行新增測試，確認在實作前失敗**

Run: `cd frontend; npm test -- src/components/ui/DevicePanel.test.tsx`

已完成紅燈階段；後續實作完成後同一組測試已通過。

## Task 2: 實作 canonical xyz 與 GPS/xyz 草稿轉換

**Files:**
- Modify: `frontend/src/components/ui/DevicePanel.tsx`

- [x] **Step 1: 加入模式型別、位置草稿型別與既有 geo imports**

```tsx
import { enuToGps, enuToThree, enuToGrid, gpsToEnu, threeToEnu } from '../../utils/geo';
import type { SceneFrame } from '../../types/sceneFrame';

type CoordMode = 'gps' | 'xyz';
type Position = [number, number, number];
type PositionDraft = Record<'lat' | 'lon' | 'alt' | 'x' | 'y' | 'z', string>;

function formatPosition(device: Device, mode: CoordMode, frame: SceneFrame): PositionDraft {
  if (mode === 'xyz') {
    return { lat: '', lon: '', alt: '', x: String(device.x), y: String(device.y), z: String(device.z) };
  }
  const gps = enuToGps(threeToEnu([device.x, device.y, device.z]), frame, frame.alt_mode);
  return { lat: String(gps.lat), lon: String(gps.lon), alt: String(gps.alt), x: '', y: '', z: '' };
}
```

Keep `formatPosition` in `DevicePanel.tsx`; it has one consumer and does not justify a new abstraction file.

- [x] **Step 2: 將數字解析與 extent 驗證集中在面板內**

```tsx
function parseNumber(value: string): number | null {
  if (!isCompleteNumber(value)) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function draftToThree(draft: PositionDraft, mode: CoordMode, frame: SceneFrame): Position | null {
  if (mode === 'xyz') {
    const values = [draft.x, draft.y, draft.z].map(parseNumber);
    return values.every((value): value is number => value !== null)
      ? [values[0], values[1], values[2]]
      : null;
  }

  const lat = parseNumber(draft.lat);
  const lon = parseNumber(draft.lon);
  const alt = parseNumber(draft.alt);
  if (lat === null || lon === null || alt === null || lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return enuToThree(gpsToEnu({ lat, lon, alt }, frame, frame.alt_mode));
}

function isInsideScene(position: Position, frame: SceneFrame): boolean {
  return enuToGrid(threeToEnu(position), frame).inside_extent;
}
```

Use `inside_extent` for both modes. Do not clamp values and do not round before storing.

- [x] **Step 3: 把 `CoordinateInput` 改為文字草稿欄位**

Give each input an accessible name such as `緯度 tx-0`, `經度 tx-0`, `高度 tx-0`, `X tx-0`, `Y tx-0`, or `Z tx-0`. Keep `type="text"` and `inputMode="decimal"` so incomplete values can remain visible until the user fixes them.

```tsx
<input
  id={inputId}
  type="text"
  inputMode="decimal"
  className={`dp-input dp-input-sm ${error ? 'has-error' : ''}`}
  value={draftValue}
  aria-label={`${label} ${device.name}`}
  aria-invalid={Boolean(error)}
  aria-describedby={errorId}
  onChange={(event) => onChange(event.target.value)}
/>
```

Do not write coordinate input changes to `useDeviceStore`; only the Apply button may call `updateDevice`.

- [x] **Step 4: 在 `DeviceRow` 維護草稿，並以 canonical 位置重置**

Add `coordMode`, `sceneFrame`, and `onApplyPosition: (position: Position) => void` props. Initialize the draft with `formatPosition(device, coordMode, sceneFrame)`. Reset it in an effect whose dependencies are `device.x`, `device.y`, `device.z`, `coordMode`, and `sceneFrame.frame_id` plus frame origin/altitude values. This drops drafts on mode/frame/canonical changes while leaving name and power behavior unchanged.

```tsx
React.useEffect(() => {
  setDraft(formatPosition(device, coordMode, sceneFrame));
  setError(null);
}, [device.x, device.y, device.z, coordMode, sceneFrame]);
```

Render GPS fields from `lat/lon/alt` and xyz fields from `x/y/z`; render the shared `error` below the coordinate group.

- [x] **Step 5: 讓套用位置只在有效且在 scene 內時更新 canonical xyz**

```tsx
const candidate = draftToThree(draft, coordMode, sceneFrame);
const draftError = candidate === null
  ? '請輸入完整且有效的座標'
  : isInsideScene(candidate, sceneFrame) ? null : '超出目前場景範圍';

const applyPosition = () => {
  if (draftError || candidate === null) return;
  onApplyPosition(candidate);
};
```

Disable the button when `candidate === null`; keep the button enabled for numeric candidates so the extent error can be shown. After `onApplyPosition`, the store update causes the draft reset effect to display the committed canonical position.

## Task 3: Wire the global mode and all-role apply flow

**Files:**
- Modify: `frontend/src/components/ui/DevicePanel.tsx`
- Modify: `frontend/src/App.tsx:500`

- [x] **Step 1: 將 `DevicePanelProps` 改為要求 `sceneFrame`**

```tsx
interface DevicePanelProps {
  sceneFrame: SceneFrame;
  onApplyRxPosition?: (pos: [number, number, number]) => void;
}
```

In `App.tsx`, pass the already computed frame without creating a second frame or changing `activeFrame` ownership:

```tsx
<DevicePanel
  sceneFrame={activeFrame}
  onApplyRxPosition={(pos) => setUavPosition(pos)}
/>
```

- [x] **Step 2: 在面板層建立單一模式按鈕**

```tsx
const [coordMode, setCoordMode] = React.useState<CoordMode>('gps');
const coordinateInputsId = React.useId();
const nextMode = coordMode === 'gps' ? 'xyz' : 'gps';

<button
  type="button"
  className="dp-coordinate-toggle"
  aria-pressed={coordMode === 'gps'}
  aria-controls={coordinateInputsId}
  aria-label={`切換為 ${nextMode === 'gps' ? 'GPS 經緯度' : 'XYZ 座標'}`}
  title={`切換為 ${nextMode === 'gps' ? 'GPS 經緯度' : 'XYZ 座標'}`}
  onClick={() => setCoordMode(nextMode)}
>
  {coordMode === 'gps' ? <GlobeIcon /> : <AxesIcon />}
</button>
```

The icon component must be local inline SVG with `aria-hidden="true"`, `viewBox="0 0 24 24"`, `fill="none"`, and `stroke="currentColor"`.

- [x] **Step 3: 讓三個 Section 都使用同一模式與套用 callback**

Pass `coordMode`, `sceneFrame`, and `coordinateInputsId` to every `Section` and `DeviceRow`. Replace the RX-only `onApplyPosition` gate with an all-role handler:

```tsx
const applyPosition = (device: Device, position: Position) => {
  updateDevice(device.id, { x: position[0], y: position[1], z: position[2] });
  if (device.role === 'rx') onApplyRxPosition?.(position);
};
```

Keep `onApplyRxPosition` for `applyDeviceDefault` and `zeroDevice` so existing RX behavior remains intact. The new coordinate Apply button must always be rendered for TX, RX, and Jammer.

- [x] **Step 4: 執行面板測試，確認 Task 1 變綠**

Run: `cd frontend; npm test -- src/components/ui/DevicePanel.test.tsx`

Expected: PASS with all new GPS/xyz, draft, extent, and accessibility tests passing.

## Task 4: Reflow the panel with existing dark-monitor styles

**Files:**
- Modify: `frontend/src/styles/main.scss:362-574`

- [x] **Step 1: 將裝置面板內容限制為 rail 可縮小寬度**

```scss
.device-panel {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}
```

Do not change `.workspace { --rail-width: clamp(292px, 23vw, 360px); }` or the existing 1099px drawer rules.

- [x] **Step 2: 移除 `dp-header` 樣式並增加座標工具列**

```scss
.dp-coordinate-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--panel-border);
}

.dp-coordinate-toggle {
  display: inline-grid;
  place-items: center;
  flex: 0 0 44px;
  width: 44px;
  height: 44px;
  padding: 0;
  color: var(--accent-cyan);
  background: transparent;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  cursor: pointer;
}

.dp-coordinate-toggle svg { width: 20px; height: 20px; }
.dp-coordinate-toggle:hover { background: rgba(0, 212, 255, 0.12); }
```

- [x] **Step 3: 將座標欄位改為單欄並保留現有色彩**

```scss
.dp-coordinate-fields {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.dp-coordinate-field {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 5px;
  min-width: 0;
}

.dp-coordinate-field .dp-input { min-width: 0; }
.dp-input.has-error { border-color: var(--danger); }

.dp-coordinate-error {
  color: var(--danger);
  font-size: 10px;
}
```

Reuse `--panel-bg`, `--panel-border`, `--text`, `--text-muted`, `--input-bg`, `--accent-cyan`, and the existing apply/danger button colors. Add a visible `:focus-visible` outline to the toggle and all buttons without introducing new color variables.

- [x] **Step 4: 檢查窄螢幕 CSS 與版面驗收**

Run: `cd frontend; npm run build`

Expected: exit code 0. Verify in the browser at desktop width and below 1099px that the rail remains `clamp(292px, 23vw, 360px)`, the drawer remains bounded by `calc(100vw - 44px)`, and no coordinate field creates horizontal overflow.

## Task 5: Full verification and handoff

**Files:**
- Verify: `frontend/src/components/ui/DevicePanel.tsx`
- Verify: `frontend/src/components/ui/DevicePanel.test.tsx`
- Verify: `frontend/src/App.tsx`
- Verify: `frontend/src/styles/main.scss`

- [x] **Step 1: 執行完整前端測試**

Run: `cd frontend; npm test`

結果：18 個測試檔、81 個測試通過。

- [x] **Step 2: 執行完整前端 build**

Run: `cd frontend; npm run build`

結果：TypeScript 檢查與 Vite bundling 通過；僅保留既有 chunk size warning。

- [x] **Step 3: 檢查 diff 與未納入的既有工作區變更**

Run: `git diff --check; git status --short`

結果：功能實作 diff 僅涉及四個前端檔案；既有地圖與場景索引變更未納入功能提交。

- [x] **Step 4: 提交最小 feature commit**

```powershell
git add frontend/src/components/ui/DevicePanel.tsx frontend/src/components/ui/DevicePanel.test.tsx frontend/src/App.tsx frontend/src/styles/main.scss
git commit -m "feat(ui): add GPS coordinate input mode"
```

功能實作已拆成多個 focused commits；本次文件更新另建立獨立 commit。
