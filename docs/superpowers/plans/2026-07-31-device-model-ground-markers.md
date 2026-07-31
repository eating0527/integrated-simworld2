# TX/Jammer Device Ground Markers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink TX and Jammer 3D models to 25% of their current rendered size and add fixed ground-level circular markers, blue for TX and green for Jammer.

**Architecture:** Add a focused `DeviceGroundMarker` scene component that owns the reusable ring/circle geometry and role color mapping. `MainScene` remains responsible for device-store visibility and composes each visible device model with its marker; CFAR rendering stays unchanged.

**Tech Stack:** React, TypeScript, React Three Fiber, Three.js, Vitest, Testing Library.

---

### Task 1: Add the tested ground-marker visual component

**Files:**
- Create: `frontend/src/components/scene/DeviceGroundMarker.tsx`
- Create: `frontend/tests/device-ground-marker.test.mjs`

- [ ] **Step 1: Write the failing visual-configuration test**

Create `frontend/tests/device-ground-marker.test.mjs` with tests for the public visual configuration. The test deliberately imports a function that does not exist yet, so it must fail before implementation.

```js
import assert from 'node:assert/strict';
import { describe, it } from 'vitest';

import {
  getDeviceGroundMarkerVisualConfig,
} from '../src/components/scene/DeviceGroundMarker.tsx';

describe('device ground marker visual config', () => {
  it('uses blue for TX and green for Jammer', () => {
    assert.equal(getDeviceGroundMarkerVisualConfig('tx').color, '#2ea8ff');
    assert.equal(getDeviceGroundMarkerVisualConfig('jammer').color, '#39e66d');
  });

  it('keeps a fixed circular footprint for both roles', () => {
    const tx = getDeviceGroundMarkerVisualConfig('tx');
    const jammer = getDeviceGroundMarkerVisualConfig('jammer');

    assert.equal(tx.diameter, jammer.diameter);
    assert.equal(tx.radius, jammer.radius);
    assert.ok(tx.diameter > 0);
    assert.equal(tx.radius, tx.diameter / 2);
  });

  it('raises the ring slightly above the ground to avoid z-fighting', () => {
    const config = getDeviceGroundMarkerVisualConfig('tx');

    assert.ok(config.ringY > 0);
    assert.ok(config.fillY > 0);
    assert.ok(config.ringY > config.fillY);
  });
});
```

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run from `frontend/`:

```powershell
npm test -- tests/device-ground-marker.test.mjs
```

Expected result: FAIL because `DeviceGroundMarker.tsx` and `getDeviceGroundMarkerVisualConfig` do not exist yet. Fix only test setup errors if they appear; do not add production code before seeing this missing-module failure.

- [ ] **Step 3: Implement the minimal marker component**

Create `frontend/src/components/scene/DeviceGroundMarker.tsx` with the role type, visual configuration, and two horizontal meshes. Keep the marker at the supplied device position; the small positive Y offsets are local to that position. Disable depth writing so the translucent marker does not obscure the scene.

```tsx
import type { ThreeElements } from '@react-three/fiber';

export type DeviceGroundMarkerRole = 'tx' | 'jammer';

interface DeviceGroundMarkerProps {
  position: [number, number, number];
  role: DeviceGroundMarkerRole;
}

const DEVICE_GROUND_MARKER_DIAMETER = 18;
const DEVICE_GROUND_MARKER_RADIUS = DEVICE_GROUND_MARKER_DIAMETER / 2;
const DEVICE_GROUND_MARKER_RING_Y = 0.35;
const DEVICE_GROUND_MARKER_FILL_Y = 0.28;

const DEVICE_GROUND_MARKER_COLORS: Record<DeviceGroundMarkerRole, string> = {
  tx: '#2ea8ff',
  jammer: '#39e66d',
};

export function getDeviceGroundMarkerVisualConfig(role: DeviceGroundMarkerRole) {
  return {
    color: DEVICE_GROUND_MARKER_COLORS[role],
    diameter: DEVICE_GROUND_MARKER_DIAMETER,
    radius: DEVICE_GROUND_MARKER_RADIUS,
    ringY: DEVICE_GROUND_MARKER_RING_Y,
    fillY: DEVICE_GROUND_MARKER_FILL_Y,
  };
}

export function DeviceGroundMarker({ position, role }: DeviceGroundMarkerProps) {
  const visual = getDeviceGroundMarkerVisualConfig(role);
  const materialProps: Pick<ThreeElements['meshBasicMaterial'], 'color' | 'transparent' | 'depthWrite'> = {
    color: visual.color,
    transparent: true,
    depthWrite: false,
  };

  return (
    <group position={position}>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, visual.ringY, 0]}>
        <ringGeometry args={[visual.radius * 0.78, visual.radius * 1.45, 64]} />
        <meshBasicMaterial {...materialProps} opacity={0.78} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, visual.fillY, 0]}>
        <circleGeometry args={[visual.radius * 0.72, 48]} />
        <meshBasicMaterial {...materialProps} opacity={0.2} />
      </mesh>
    </group>
  );
}
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
npm test -- tests/device-ground-marker.test.mjs
```

Expected result: all three device-marker tests PASS.

- [ ] **Step 5: Commit the focused component change**

```powershell
git add -- frontend/src/components/scene/DeviceGroundMarker.tsx frontend/tests/device-ground-marker.test.mjs
git commit -m "feat(scene): add device ground markers"
```

### Task 2: Compose markers in MainScene and apply quarter-size models

**Files:**
- Modify: `frontend/src/components/scene/MainScene.tsx`
- Modify: `frontend/src/components/scene/MainScene.test.tsx`

- [ ] **Step 1: Extend MainScene tests with observable model and marker props**

Update the existing mocks in `frontend/src/components/scene/MainScene.test.tsx` so the test can observe the new props, then add one focused test. Replace the current `Jam` and `Tower` mocks with:

```tsx
vi.mock('./Jam', () => ({
  Jam: ({ scale }: { scale?: number }) => (
    <div data-testid="jam-model" data-scale={String(scale)} />
  ),
}));
vi.mock('./Tower', () => ({
  Tower: ({ scale }: { scale?: number }) => (
    <div data-testid="tx-model" data-scale={String(scale)} />
  ),
}));
vi.mock('./DeviceGroundMarker', () => ({
  DeviceGroundMarker: ({
    role,
    position,
  }: {
    role: 'tx' | 'jammer';
    position: [number, number, number];
  }) => (
    <div
      data-testid={`${role}-ground-marker`}
      data-position={position.join(',')}
    />
  ),
}));
```

Add this test inside `describe('MainScene device visibility', ...)`:

```tsx
it('renders quarter-size TX/Jammer models with matching ground markers', () => {
  render(<MainScene />);

  expect(screen.getAllByTestId('tx-model')).toHaveLength(2);
  expect(screen.getAllByTestId('tx-model').every((model) => model.getAttribute('data-scale') === '0.025')).toBe(true);
  expect(screen.getAllByTestId('jam-model')).toHaveLength(1);
  expect(screen.getByTestId('jam-model')).toHaveAttribute('data-scale', '0.0025');
  expect(screen.getAllByTestId('tx-ground-marker')).toHaveLength(2);
  expect(screen.getAllByTestId('jammer-ground-marker')).toHaveLength(1);
  expect(screen.getByTestId('tx-ground-marker')).toHaveAttribute('data-position', '1,2,3');
  expect(screen.getByTestId('jammer-ground-marker')).toHaveAttribute('data-position', '7,8,9');
});
```

- [ ] **Step 2: Run the MainScene test and verify the expected failure**

Run:

```powershell
npm test -- src/components/scene/MainScene.test.tsx
```

Expected result: FAIL because `MainScene` does not yet render `DeviceGroundMarker` and still passes `0.1`/`0.01` to the model components.

- [ ] **Step 3: Integrate the marker and quarter-size constants in MainScene**

In `frontend/src/components/scene/MainScene.tsx`, import `DeviceGroundMarker`, declare the two explicit scale constants near the component imports, and replace the existing TX/Jammer render blocks with the following. Keep the existing `modelVisible` conditions and `Suspense` boundaries unchanged.

```tsx
import { DeviceGroundMarker } from './DeviceGroundMarker';

const TX_MODEL_SCALE = 0.025;
const JAMMER_MODEL_SCALE = 0.0025;
```

```tsx
        {modelVisible.jammer && jammerDevices.map((d) => (
          <Suspense key={d.id} fallback={null}>
            <Jam position={[d.x, d.y, d.z]} scale={JAMMER_MODEL_SCALE} />
            <DeviceGroundMarker position={[d.x, d.y, d.z]} role="jammer" />
          </Suspense>
        ))}

        {modelVisible.tx && txDevices.map((d) => (
          <Suspense key={d.id} fallback={null}>
            <Tower position={[d.x, d.y, d.z]} scale={TX_MODEL_SCALE} />
            <DeviceGroundMarker position={[d.x, d.y, d.z]} role="tx" />
          </Suspense>
        ))}
```

Do not alter `CFARBeaconMarker`, `cfarBeacons`, device-store state, or coordinate conversion code.

- [ ] **Step 4: Run the MainScene and marker tests and verify they pass**

Run:

```powershell
npm test -- tests/device-ground-marker.test.mjs src/components/scene/MainScene.test.tsx
```

Expected result: all focused tests PASS, including the existing visibility tests. The hidden-role cases must show zero models and zero markers for the hidden role while retaining the other role and RX model.

- [ ] **Step 5: Run the complete frontend test suite**

Run:

```powershell
npm test
```

Expected result: the complete Vitest suite PASS with no new warnings or errors.

- [ ] **Step 6: Type-check and build the frontend**

Run:

```powershell
npm run build
```

Expected result: TypeScript checking and Vite production build complete successfully.

- [ ] **Step 7: Commit the MainScene integration**

```powershell
git add -- frontend/src/components/scene/MainScene.tsx frontend/src/components/scene/MainScene.test.tsx
git commit -m "feat(scene): resize device models and mark bases"
```

### Task 3: Final regression review

**Files:**
- Inspect: `frontend/src/components/scene/CFARBeaconMarker.tsx`
- Inspect: `frontend/tests/cfar-beacon-marker.test.mjs`
- Inspect: `git diff HEAD~2..HEAD`

- [ ] **Step 1: Confirm CFAR behavior remains isolated**

Run:

```powershell
npm test -- tests/cfar-beacon-marker.test.mjs
```

Expected result: the existing CFAR visual configuration tests PASS without changes to CFAR dimensions, height, label configuration, or red marker behavior.

- [ ] **Step 2: Confirm the final worktree and diff are scoped**

Run:

```powershell
git status --short
git diff --check HEAD~2..HEAD
```

Expected result: no whitespace errors and no generated assets, logs, captures, or unrelated files in the feature commits.
