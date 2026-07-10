# Frontend Workspace Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將桌面前端整理為頂部場景列、左右可收合工作欄與可垂直縮放面板，同時保持所有既有資料流與後端工作流不變。

**Architecture:** 新增單一 `Workspace` UI 殼層負責左右欄與窄螢幕抽屜狀態，`App` 只把既有功能元件放入對應插槽。沿用並簡化 `MinPanel` 作為共同面板外框，所有視覺與響應式規則集中在既有 `main.scss`，不新增執行期依賴或全域 store。

**Tech Stack:** React 19、TypeScript、SCSS、Vitest、Testing Library、Vite

---

## 檔案配置

- 新增 `frontend/src/components/ui/Workspace.tsx`：工作區、左右欄、桌面隱藏與窄螢幕互斥抽屜。
- 新增 `frontend/src/components/ui/Workspace.test.tsx`：工作欄與抽屜互動測試。
- 修改 `frontend/src/components/ui/MinPanel.tsx`：共用收合、可存取狀態與預設收合。
- 修改 `frontend/src/components/ui/MinPanel.test.tsx`：移除自由拖曳測試，改測停靠面板行為。
- 新增 `frontend/src/components/ui/SceneSwitcher.test.tsx`：場景列回呼、下拉與鍵盤測試。
- 修改 `frontend/src/components/ui/SceneSwitcher.tsx`：語意化導覽與 class-based 樣式。
- 修改 `frontend/src/App.tsx`：把既有功能元件分配至工作區插槽。
- 修改 `frontend/src/components/ui/{UAVControlPanel,AircraftTelemetry,GPSStatus,ControllerScreenPanel,USRPTelemetry,SimulationPanel,PhotoViewer}.tsx`：移除獨立浮動定位與重複開關，保留內部功能。
- 修改 `frontend/src/components/ui/PanelUi.tsx`：刪除不再使用的硬編碼 `PANEL_POS`。
- 修改 `frontend/src/components/ui/SimulationPanel.test.tsx`：面板改為直接停靠後仍保留八個頁籤與請求測試。
- 修改 `frontend/src/styles/main.scss`：工作區、場景列、面板與響應式視覺規則。

### Task 1: 簡化並強化共用 MinPanel

**Files:**
- Modify: `frontend/src/components/ui/MinPanel.test.tsx`
- Modify: `frontend/src/components/ui/MinPanel.tsx`

- [ ] **Step 1: 先寫失敗測試**

以以下測試取代拖曳與固定座標案例，保留既有收合／恢復案例：

```tsx
it('reports expansion state and keeps collapsed children mounted but inert', async () => {
  const user = userEvent.setup();
  const { container } = render(
    <MinPanel title="連線狀態">
      <button>改名</button>
    </MinPanel>,
  );
  const title = screen.getByRole('button', { name: /minimize 連線狀態/i });

  expect(title).toHaveAttribute('aria-expanded', 'true');
  await user.click(title);

  expect(screen.queryByRole('button', { name: '改名' })).not.toBeInTheDocument();
  expect(container.querySelector('.min-panel__body')).toHaveAttribute('inert');
  expect(container.querySelector('.min-panel__body button')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /restore 連線狀態/i })).toHaveAttribute('aria-expanded', 'false');
});

it('supports an initially collapsed secondary panel', () => {
  const { container } = render(
    <MinPanel title="照片" defaultMinimized>
      <button>開啟照片</button>
    </MinPanel>,
  );

  expect(screen.getByRole('button', { name: /restore 照片/i })).toHaveAttribute('aria-expanded', 'false');
  expect(container.querySelector('.min-panel__body button')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '開啟照片' })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: 執行測試確認 RED**

Run:

```powershell
Set-Location frontend
npm test -- src/components/ui/MinPanel.test.tsx
```

Expected: FAIL，`defaultMinimized` 尚不存在，標題按鈕也沒有 `aria-expanded`。

- [ ] **Step 3: 實作最小共用面板**

以 `useId`、`useState` 取代拖曳位置狀態；保留既有 props，新增 `defaultMinimized?: boolean`，刪除 `draggable`：

```tsx
import type React from 'react';
import { useId, useState } from 'react';

interface MinPanelProps {
  title: string;
  children: React.ReactNode;
  as?: 'div' | 'aside';
  className?: string;
  style?: React.CSSProperties;
  bodyClassName?: string;
  bodyStyle?: React.CSSProperties;
  actions?: React.ReactNode;
  defaultMinimized?: boolean;
}

export function MinPanel({
  title,
  children,
  as = 'div',
  className = '',
  style,
  bodyClassName = '',
  bodyStyle,
  actions,
  defaultMinimized = false,
}: MinPanelProps) {
  const [minimized, setMinimized] = useState(defaultMinimized);
  const bodyId = useId();
  const Root = as;

  return (
    <Root className={`${className} min-panel ${minimized ? 'is-min' : ''}`.trim()} style={style}>
      <div className="min-panel__bar">
        <button
          type="button"
          className="min-panel__title-btn"
          aria-label={`${minimized ? 'Restore' : 'Minimize'} ${title}`}
          aria-expanded={!minimized}
          aria-controls={bodyId}
          onClick={() => setMinimized(value => !value)}
        >
          <span>{title}</span>
          <span className="min-panel__chevron" aria-hidden="true">⌄</span>
        </button>
        {!minimized && actions}
      </div>
      <div
        id={bodyId}
        className={`min-panel__body ${bodyClassName}`.trim()}
        aria-hidden={minimized}
        inert={minimized ? true : undefined}
        style={bodyStyle}
      >
        <div className="min-panel__body-inner">{children}</div>
      </div>
    </Root>
  );
}
```

- [ ] **Step 4: 執行測試確認 GREEN**

```powershell
npm test -- src/components/ui/MinPanel.test.tsx
```

Expected: `MinPanel.test.tsx` 全部通過。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/components/ui/MinPanel.tsx frontend/src/components/ui/MinPanel.test.tsx
git commit -m "refactor: simplify docked panel shell"
```

### Task 2: 建立左右工作區殼層

**Files:**
- Create: `frontend/src/components/ui/Workspace.test.tsx`
- Create: `frontend/src/components/ui/Workspace.tsx`

- [ ] **Step 1: 先寫工作區失敗測試**

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Workspace } from './Workspace';

function renderWorkspace() {
  return render(
    <Workspace top={<div>場景列</div>} left={<div>左側內容</div>} right={<div>右側內容</div>}>
      <div>3D 場景</div>
    </Workspace>,
  );
}

describe('Workspace', () => {
  it('toggles desktop rails independently', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const leftToggle = screen.getByRole('button', { name: '切換左側工作區' });
    const rightToggle = screen.getByRole('button', { name: '切換右側工作區' });
    expect(leftToggle).toHaveAttribute('aria-expanded', 'true');
    expect(rightToggle).toHaveAttribute('aria-expanded', 'true');

    await user.click(leftToggle);
    expect(leftToggle).toHaveAttribute('aria-expanded', 'false');
    expect(rightToggle).toHaveAttribute('aria-expanded', 'true');
  });

  it('keeps narrow-screen drawers mutually exclusive and closes them with Escape', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const left = screen.getByRole('button', { name: '開啟左側工作區' });
    const right = screen.getByRole('button', { name: '開啟右側工作區' });
    await user.click(left);
    expect(left).toHaveAttribute('aria-expanded', 'true');
    await user.click(right);
    expect(left).toHaveAttribute('aria-expanded', 'false');
    expect(right).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard('{Escape}');
    expect(right).toHaveAttribute('aria-expanded', 'false');
  });
});
```

- [ ] **Step 2: 執行測試確認 RED**

```powershell
npm test -- src/components/ui/Workspace.test.tsx
```

Expected: FAIL，`Workspace` 模組尚不存在。

- [ ] **Step 3: 實作最小 Workspace**

```tsx
import { useEffect, useState, type ReactNode } from 'react';

type Rail = 'left' | 'right';

interface WorkspaceProps {
  top?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
}

export function Workspace({ top, left, right, children }: WorkspaceProps) {
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [mobileRail, setMobileRail] = useState<Rail | null>(null);

  useEffect(() => {
    const closeDrawer = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileRail(null);
    };
    window.addEventListener('keydown', closeDrawer);
    return () => window.removeEventListener('keydown', closeDrawer);
  }, []);

  const toggleMobile = (rail: Rail) => setMobileRail(current => current === rail ? null : rail);

  return (
    <div className="workspace">
      <main className="workspace__stage">{children}</main>
      {top && <header className="workspace__top">{top}</header>}

      {left && (
        <aside id="workspace-left" className={`workspace__rail workspace__rail--left ${leftOpen ? 'is-open' : ''} ${mobileRail === 'left' ? 'is-mobile-open' : ''}`}>
          {left}
        </aside>
      )}
      {right && (
        <aside id="workspace-right" className={`workspace__rail workspace__rail--right ${rightOpen ? 'is-open' : ''} ${mobileRail === 'right' ? 'is-mobile-open' : ''}`}>
          {right}
        </aside>
      )}

      <div className="workspace__rail-controls" aria-label="工作區顯示控制">
        {left && <button type="button" aria-label="切換左側工作區" aria-expanded={leftOpen} aria-controls="workspace-left" onClick={() => setLeftOpen(value => !value)}>‹</button>}
        {right && <button type="button" aria-label="切換右側工作區" aria-expanded={rightOpen} aria-controls="workspace-right" onClick={() => setRightOpen(value => !value)}>›</button>}
      </div>

      <div className="workspace__drawer-controls" aria-label="行動工作區控制">
        {left && <button type="button" aria-label="開啟左側工作區" aria-expanded={mobileRail === 'left'} aria-controls="workspace-left" onClick={() => toggleMobile('left')}>控制</button>}
        {right && <button type="button" aria-label="開啟右側工作區" aria-expanded={mobileRail === 'right'} aria-controls="workspace-right" onClick={() => toggleMobile('right')}>狀態</button>}
      </div>

      {mobileRail && <button type="button" className="workspace__backdrop" aria-label="關閉側欄" onClick={() => setMobileRail(null)} />}
    </div>
  );
}
```

- [ ] **Step 4: 執行測試確認 GREEN**

```powershell
npm test -- src/components/ui/Workspace.test.tsx
```

Expected: 2 tests passed。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/components/ui/Workspace.tsx frontend/src/components/ui/Workspace.test.tsx
git commit -m "feat: add responsive workspace shell"
```

### Task 3: 整理頂部場景選擇器

**Files:**
- Create: `frontend/src/components/ui/SceneSwitcher.test.tsx`
- Modify: `frontend/src/components/ui/SceneSwitcher.tsx`
- Modify: `frontend/src/styles/main.scss`

- [ ] **Step 1: 先寫場景列失敗測試**

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { SceneSwitcher } from './SceneSwitcher';

const generated = [{ taskId: 'task-1', sceneKey: 'custom', label: '自訂場景', modelPath: '/scene.glb', createdAt: '2026-07-10' }];

describe('SceneSwitcher', () => {
  it('uses navigation semantics and preserves preset/generated callbacks', async () => {
    const user = userEvent.setup();
    const onSelectPreset = vi.fn();
    const onSelectGenerated = vi.fn();
    render(<SceneSwitcher selectedScene={{ source: 'preset', id: 'ntpu' }} generatedScenes={generated} onSelectPreset={onSelectPreset} onSelectGenerated={onSelectGenerated} />);

    expect(screen.getByRole('navigation', { name: '場景選擇' })).toHaveClass('scene-switcher');
    await user.click(screen.getByRole('button', { name: /NYCU/i }));
    expect(onSelectPreset).toHaveBeenCalledWith('nycu');
    await user.click(screen.getByRole('button', { name: /generated/i }));
    await user.click(screen.getByRole('option', { name: '自訂場景' }));
    expect(onSelectGenerated).toHaveBeenCalledWith('task-1');
  });

  it('closes the generated scene list with Escape', async () => {
    const user = userEvent.setup();
    render(<SceneSwitcher selectedScene={{ source: 'preset', id: 'ntpu' }} generatedScenes={generated} onSelectPreset={() => {}} onSelectGenerated={() => {}} />);
    await user.click(screen.getByRole('button', { name: /generated/i }));
    expect(screen.getByRole('listbox', { name: 'Generated scenes' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox', { name: 'Generated scenes' })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 執行測試確認 RED**

```powershell
npm test -- src/components/ui/SceneSwitcher.test.tsx
```

Expected: 第一個測試 FAIL，現有根節點不是具名 `navigation`。

- [ ] **Step 3: 將行內視覺轉為語意與 class**

保持現有 state、effects 與回呼，將根節點與按鈕改為以下 class 結構；刪除 `buttonBaseStyle`、`subtitleStyle`、`generatedDisplayStyle`、`generatedTextStackStyle`、`generatedMenuStyle`、`generatedOptionBaseStyle`：

```tsx
<nav className="scene-switcher" aria-label="場景選擇">
  <span className="scene-switcher__eyebrow">SCENE</span>
  <div className="scene-switcher__presets">
    {SCENES.map(scene => {
      const active = selectedScene.source === 'preset' && selectedScene.id === scene.id;
      return (
        <button key={scene.id} type="button" className={`scene-switcher__button ${active ? 'is-active' : ''}`} aria-pressed={active} onClick={() => onSelectPreset(scene.id)} title={scene.label}>
          <span>{scene.labelEn}</span>
          <span className="scene-switcher__subtitle">{scene.label}</span>
        </button>
      );
    })}
  </div>
  <div ref={generatedContainerRef} className={`scene-switcher__generated ${generatedActive ? 'is-active' : ''}`}>
    <button type="button" className="scene-switcher__generated-button" aria-haspopup="listbox" aria-expanded={generatedOpen} disabled={!hasGeneratedScenes} onClick={() => hasGeneratedScenes && setGeneratedOpen(open => !open)}>
      <span><strong>Generated</strong><span className="scene-switcher__subtitle">{generatedLabel}</span></span>
      <span className="scene-switcher__chevron" aria-hidden="true">⌄</span>
    </button>
    {generatedOpen && (
      <div className="scene-switcher__menu gen-menu" role="listbox" aria-label="Generated scenes">
        {generatedScenes.map(scene => {
          const selected = selectedGeneratedScene?.taskId === scene.taskId;
          return <button key={scene.taskId} type="button" role="option" aria-selected={selected} className={`scene-switcher__option ${selected ? 'is-active' : ''}`} onClick={() => { onSelectGenerated(scene.taskId); setGeneratedOpen(false); }}>{scene.label}</button>;
        })}
      </div>
    )}
  </div>
</nav>
```

外部點擊與 Escape effects 保留，但兩個 handler 關閉選單時只呼叫 `setGeneratedOpen(false)`。刪除只為行內樣式服務的 `generatedHovered`、`generatedFocused`、`hoveredGeneratedTaskId` state，以及不再使用的 `generatedInteractive`、`generatedMuted` 常數；移除對應的 mouse、focus、blur handlers。

- [ ] **Step 4: 加入場景列 SCSS**

在 `main.scss` 加入：

```scss
.scene-switcher { display: flex; align-items: stretch; gap: 6px; max-width: 100%; padding: 6px; border: 1px solid var(--panel-border); border-radius: 12px; background: var(--panel-bg); box-shadow: 0 12px 34px rgba(0, 0, 0, 0.34); backdrop-filter: blur(18px); }
.scene-switcher__eyebrow { align-self: center; padding: 0 8px; color: var(--text-dim); font: 700 10px/1 monospace; letter-spacing: 0.14em; }
.scene-switcher__presets { display: flex; gap: 4px; min-width: 0; overflow-x: auto; }
.scene-switcher__button, .scene-switcher__generated-button, .scene-switcher__option { border: 1px solid transparent; background: transparent; color: var(--text-secondary); cursor: pointer; }
.scene-switcher__button { min-width: 92px; padding: 6px 12px; border-radius: 8px; }
.scene-switcher__button.is-active, .scene-switcher__generated.is-active .scene-switcher__generated-button { border-color: rgba(112, 211, 198, 0.35); background: rgba(112, 211, 198, 0.14); color: var(--accent-strong); }
.scene-switcher__subtitle { display: block; max-width: 132px; margin-top: 2px; overflow: hidden; color: var(--text-dim); font-size: 10px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.scene-switcher__generated { position: relative; min-width: 156px; }
.scene-switcher__generated-button { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; height: 100%; padding: 6px 12px; border-radius: 8px; text-align: left; }
.scene-switcher__menu { position: absolute; top: calc(100% + 10px); right: 0; z-index: 2; width: min(280px, calc(100vw - 24px)); max-height: 280px; padding: 6px; overflow-y: auto; border: 1px solid var(--panel-border); border-radius: 10px; background: rgba(7, 12, 19, 0.98); box-shadow: 0 18px 44px rgba(0, 0, 0, 0.48); }
.scene-switcher__option { display: block; width: 100%; padding: 9px 10px; border-radius: 7px; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.scene-switcher__option:hover, .scene-switcher__option.is-active { background: rgba(112, 211, 198, 0.14); color: var(--accent-strong); }
.scene-switcher :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

- [ ] **Step 5: 執行測試確認 GREEN**

```powershell
npm test -- src/components/ui/SceneSwitcher.test.tsx
```

Expected: 2 tests passed。

- [ ] **Step 6: 提交**

```powershell
git add frontend/src/components/ui/SceneSwitcher.tsx frontend/src/components/ui/SceneSwitcher.test.tsx frontend/src/styles/main.scss
git commit -m "refactor: streamline scene switcher"
```

### Task 4: 將既有面板改為停靠內容

**Files:**
- Modify: `frontend/src/components/ui/UAVControlPanel.tsx`
- Modify: `frontend/src/components/ui/AircraftTelemetry.tsx`
- Modify: `frontend/src/components/ui/GPSStatus.tsx`
- Modify: `frontend/src/components/ui/ControllerScreenPanel.tsx`
- Modify: `frontend/src/components/ui/USRPTelemetry.tsx`
- Modify: `frontend/src/components/ui/SimulationPanel.tsx`
- Modify: `frontend/src/components/ui/PhotoViewer.tsx`
- Modify: `frontend/src/components/ui/PanelUi.tsx`
- Modify: `frontend/src/components/ui/SimulationPanel.test.tsx`

- [ ] **Step 1: 先修改模擬面板測試，使新需求 RED**

將 `openPanel` 改為只 render，並以共用標題列控制收合：

```tsx
async function openPanel() {
  const user = userEvent.setup();
  render(<SimulationPanel sceneId="NTPU" />);
  return user;
}

it('renders docked and collapses through the shared panel shell', async () => {
  const user = await openPanel();
  expect(screen.getByRole('button', { name: 'SINR Map' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /minimize 無線通道模擬/i }));
  expect(screen.queryByRole('button', { name: 'SINR Map' })).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /restore 無線通道模擬/i }));
  expect(screen.getByRole('button', { name: 'SINR Map' })).toBeInTheDocument();
});
```

刪除同檔其他測試中所有點擊 `/sionna/i` 的開啟步驟；其他八頁籤、payload、overlay、錯誤與 modal assertions 原封不動。

- [ ] **Step 2: 執行測試確認 RED**

```powershell
npm test -- src/components/ui/SimulationPanel.test.tsx
```

Expected: FAIL，現有模擬內容預設未掛載。

- [ ] **Step 3: 移除各面板獨立浮動狀態**

對 `UAVControlPanel.tsx` 執行以下精確編輯：刪除目前第 230 行的 `open` state；刪除 `return` 後從 `onClick={() => setOpen(v => !v)}` 所在 `<button>` 到其 `</button>` 的整個固定觸發按鈕；刪除 `{open && (` 與對應的 `)}`；把 `MinPanel` 開始標籤換成下列內容，檔案尾端只保留一組 `</MinPanel>`：

```tsx
return (
  <MinPanel title="無人機控制" className="panel-ui uav-control-panel">
    <div style={{ ...S.panel, borderRadius: 0, border: 'none', boxShadow: 'none' }}>
```

此開始標籤之後緊接現有 Mode toggles；Coordinates JSX 結束後使用以下結尾：

```tsx
    </div>
  </MinPanel>
);
```

對 `SimulationPanel.tsx` 執行以下精確編輯：刪除第 143 行的 `open` state；刪除 `return` 後 `aria-label="Sionna simulation panel"` 的完整固定按鈕；刪除 `{open && (` 與對應 `)}`；將 `MinPanel` 開始標籤換成下列內容；刪除 `aria-label="Close simulation panel"` 的按鈕及其只含標題的父 `<div>`：

```tsx
return (
  <>
    <MinPanel title="無線通道模擬" className="panel-ui simulation-panel">
```

此開始標籤之後緊接現有「頁籤」註解；目前結果區後方的 `</MinPanel>` 保留，接著保持現有 `preview && (...)` modal JSX 與 fragment 結尾不變。

對 `AircraftTelemetry`、`GPSStatus`、`ControllerScreenPanel`、`USRPTelemetry` 的 `MinPanel` 移除 `draggable` 與 `PANEL_POS`；保留各自 `className`、`actions`、children 及業務 props。
```

`AircraftTelemetry` 的 `compact` 手機定位例外保留；桌面 `style` 改為 `undefined`。`GPSStatus` 的可選 `style` 僅保留呼叫者傳入值。`PanelUi.tsx` 刪除 `PANEL_POS` export。

`PhotoViewer` 將 `collapsed` 初值改為 `true`，外層改成 `className="photo-viewer panel-ui"`，移除 `position`、`bottom`、`right`、`zIndex` 與固定寬度；lightbox 的 fixed overlay 保留。

- [ ] **Step 4: 執行面板測試確認 GREEN**

```powershell
npm test -- src/components/ui/SimulationPanel.test.tsx src/components/ui/AircraftTelemetry.test.tsx src/components/ui/GPSStatus.test.tsx src/components/ui/ControllerScreenPanel.test.tsx src/components/ui/USRPTelemetry.test.tsx
```

Expected: 所列測試全數通過，模擬請求 assertions 未改變。

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/components/ui
git commit -m "refactor: dock operational panels"
```

### Task 5: 在 App 接入工作區，不改資料流

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 先以 TypeScript 建置確認 Workspace 尚未接入**

```powershell
Select-String -Path src/App.tsx -Pattern '<Workspace'
```

Expected: 無輸出。

- [ ] **Step 2: 將現有 JSX 放入工作區插槽**

新增 import：

```tsx
import { Workspace } from './components/ui/Workspace';
```

在 render 前建立既有面板元素，props 與 callback 完全沿用：

```tsx
const aircraftPanel = (
  <AircraftTelemetry deviceId={aircraftEntry?.[0] ?? null} device={aircraftEntry?.[1] ?? null} isTracked={Boolean(aircraftEntry && selectedDeviceId === aircraftEntry[0])} compact={isMobile} onTrack={() => { if (aircraftEntry) setSelectedDeviceId(aircraftEntry[0]); }} />
);
const gpsPanel = (
  <GPSStatus myDeviceId={myDeviceId} deviceName={deviceName} onRenameClick={handleRename} allDevices={allDevices} uavPath={uavPath} onClearPath={handleClearPath} connectionStatus={connectionStatus} localGPS={currentGPS} selectedDeviceId={selectedDeviceId} onSelectDevice={setSelectedDeviceId} />
);
```

以以下結構取代原本散落的面板 JSX：

```tsx
<Workspace
  top={!isMobile ? <SceneSwitcher selectedScene={selectedScene} generatedScenes={generatedScenes.scenes} generatedStatus={generatedScenes.status} onSelectPreset={id => { setLastPresetSceneId(id); setSelectedScene({ source: 'preset', id }); }} onSelectGenerated={taskId => setSelectedScene({ source: 'generated', taskId })} /> : undefined}
  left={!isMobile ? <><DevicePanel onApplyRxPosition={pos => setUavPosition(pos)} /><UAVControlPanel auto={auto} uavAnimation={uavAnimation} uavPosition={uavPosition} onToggleAuto={handleToggleAuto} onToggleAnimation={() => setUavAnimation(prev => !prev)} onManualControl={handleManualControl} /><USRPTelemetry /></> : undefined}
  right={!isMobile ? <>
    {aircraftPanel}
    {gpsPanel}
    <ControllerScreenPanel />
    <SimulationPanel
      sceneId={simulationSceneId}
      generatedScene={simulationUsesGeneratedScene}
      onCfarClustersChange={setCfarClusters}
      onHeatmapOverlayChange={setHeatmapOverlay}
      onRouteOverlayChange={setIssRouteOverlay}
      gpsReplayRate={gpsReplayRate}
      gpsReplayPlaying={gpsReplayPlaying}
      onGpsReplayPlay={handleGpsReplayPlay}
      onGpsReplayPause={handleGpsReplayPause}
      onGpsReplayStop={handleGpsReplayStop}
      onGpsReplayRateChange={setGpsReplayRate}
    />
    <PhotoViewer photos={photos} onDelete={handleDelete} />
  </> : undefined}
>
  <MainScene
    uavPosition={uavPosition}
    uavPath={uavPath}
    sceneId={renderSceneId}
    auto={auto}
    manualDirection={manualDirection}
    onManualMoveDone={handleManualMoveDone}
    uavAnimation={uavAnimation}
    otherUavs={otherUavs}
    cfarBeacons={cfarBeacons}
    heatmapOverlay={heatmapOverlay}
    issRouteOverlay={issRouteOverlay}
    generatedSceneModelPath={activeGeneratedScene?.modelPath}
    onPositionUpdate={pos => {
      setUavPosition(pos);
      setUavPath(prev => {
        const last = prev[prev.length - 1];
        if (last && Math.abs(last.x - pos[0]) < 0.1 && Math.abs(last.z - pos[2]) < 0.1) return prev;
        return [...prev, { x: pos[0], y: pos[1], z: pos[2] }];
      });
    }}
  />
  {isMobile && aircraftPanel}
  {isMobile && gpsPanel}
  <CameraUpload currentPosition={currentGPS ? { lat: currentGPS.lat, lon: currentGPS.lon, altitude: currentGPS.alt } : null} deviceId={myDeviceId} />
</Workspace>
```

- [ ] **Step 3: 執行 TypeScript 與現有功能測試**

```powershell
npm test
npm run build
```

Expected: 全部測試通過，`tsc` 與 Vite build exit code 0。

- [ ] **Step 4: 提交**

```powershell
git add frontend/src/App.tsx
git commit -m "feat: arrange panels in workspace"
```

### Task 6: 完成統一樣式與響應式規則

**Files:**
- Modify: `frontend/src/styles/main.scss`

- [ ] **Step 1: 移除舊浮動定位樣式**

刪除或改寫 `.device-panel`、`.controller-screen-panel`、`.sim-panel` 與 `.min-panel.is-min` 中依賴全畫面 fixed/absolute/max-content 的規則。模擬 modal、照片 lightbox 與手機 HUD 的 overlay 規則保留。

- [ ] **Step 2: 加入完整工作區與共用面板 SCSS**

```scss
:root {
  --panel-bg: rgba(9, 14, 22, 0.9);
  --panel-surface: rgba(18, 29, 40, 0.78);
  --panel-border: rgba(112, 211, 198, 0.2);
  --panel-radius: 10px;
  --accent: #70d3c6;
  --accent-strong: #9ff3e7;
  --warning: #f3b45d;
  --danger: #ff6b6b;
  --text-primary: #eef8f6;
  --text-secondary: #a8bfba;
  --text-dim: #718681;
  --workspace-gap: 12px;
  --workspace-top: 76px;
  --rail-width: clamp(292px, 23vw, 360px);
}

.workspace { position: relative; width: 100vw; height: 100dvh; overflow: hidden; color: var(--text-primary); }
.workspace__stage { position: absolute; inset: 0; }
.workspace__top { position: fixed; top: 12px; left: 50%; z-index: 1100; max-width: calc(100vw - 96px); transform: translateX(-50%); }
.workspace__rail { position: fixed; top: var(--workspace-top); bottom: var(--workspace-gap); z-index: 1000; width: var(--rail-width); display: flex; flex-direction: column; gap: 10px; overflow-x: hidden; overflow-y: auto; scrollbar-width: thin; transition: transform 180ms ease, opacity 180ms ease; }
.workspace__rail--left { left: var(--workspace-gap); transform: translateX(calc(-100% - 24px)); }
.workspace__rail--right { right: var(--workspace-gap); transform: translateX(calc(100% + 24px)); }
.workspace__rail.is-open { transform: translateX(0); }
.workspace__rail > * { flex: 0 0 auto; width: 100% !important; min-width: 0 !important; inset: auto !important; }
.workspace__rail .min-panel:not(.is-min) { min-height: 112px; max-height: calc(100dvh - 100px); resize: vertical; overflow: hidden auto; }
.workspace__rail-controls { position: fixed; inset: 50% 8px auto; z-index: 1050; display: flex; justify-content: space-between; pointer-events: none; }
.workspace__rail-controls button, .workspace__drawer-controls button { min-width: 44px; min-height: 44px; pointer-events: auto; }
.workspace__drawer-controls { display: none; }
.workspace__backdrop { display: none; }

.min-panel { background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: var(--panel-radius); box-shadow: 0 14px 36px rgba(0, 0, 0, 0.32); backdrop-filter: blur(16px); }
.min-panel__bar { min-height: 44px; }
.min-panel__title-btn { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--accent-strong); }
.min-panel__chevron { transition: transform 160ms ease; }
.min-panel.is-min .min-panel__chevron { transform: rotate(-90deg); }
.min-panel.is-min .min-panel__body { grid-template-rows: 0fr; opacity: 0; pointer-events: none; }
.min-panel__body-inner { overflow: hidden; }
.min-panel:not(.is-min) .min-panel__body-inner { overflow: auto; }
.photo-viewer { width: 100%; }

@media (max-width: 1099px) {
  .workspace__rail-controls { display: none; }
  .workspace__drawer-controls { position: fixed; right: 12px; bottom: 12px; z-index: 1120; display: flex; gap: 8px; }
  .workspace__rail { top: 68px; width: min(360px, calc(100vw - 28px)); transform: translateX(calc(-100% - 28px)); }
  .workspace__rail--right { left: 14px; right: auto; }
  .workspace__rail.is-open { transform: translateX(calc(-100% - 28px)); }
  .workspace__rail.is-mobile-open { transform: translateX(0); }
  .workspace__backdrop { position: fixed; inset: 0; z-index: 990; display: block; border: 0; background: rgba(2, 7, 12, 0.56); backdrop-filter: blur(2px); }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
}
```

- [ ] **Step 3: 執行完整驗證**

```powershell
npm test
npm run build
```

Expected: 所有 Vitest 測試通過，production build exit code 0，無 TypeScript 或 Sass 錯誤。

- [ ] **Step 4: 提交**

```powershell
git add frontend/src/styles/main.scss
git commit -m "style: unify mission workspace"
```

### Task 7: 完成條件稽核與視覺驗證

**Files:**
- Verify only

- [ ] **Step 1: 檢查不應殘留的桌面浮動定位**

```powershell
Select-String -Path src/components/ui/*.tsx -Pattern 'PANEL_POS','draggable','position:.*fixed' | Select-Object Path,LineNumber,Line
```

Expected: `PANEL_POS` 與 `draggable` 無結果；`position: fixed` 只允許 modal、lightbox 或手機專用 overlay，不得出現在七個桌面面板外框。

- [ ] **Step 2: 檢查無線模擬八個頁籤仍存在**

```powershell
Select-String -Path src/components/ui/SimulationPanel.tsx -Pattern "key: 'sinr'","key: 'cfr'","key: 'doppler'","key: 'channel'","key: 'iss'","key: 'tss'","key: 'cfar'","key: 'iss_unet'"
```

Expected: 八個 key 全部找到。

- [ ] **Step 3: 重新執行完整測試與建置**

```powershell
npm test
npm run build
```

Expected: 0 failed tests；build exit code 0。

- [ ] **Step 4: 以可用瀏覽器檢查兩種寬度**

桌面寬螢幕檢查頂部列、左右欄、欄內捲動、七個面板收合與縮放；約 1000px 寬度檢查左右抽屜互斥、背景遮罩與 Escape。若內嵌瀏覽器仍不可用，在交付訊息明列「未取得瀏覽器視覺證據」，不得改用建置結果宣稱視覺驗證完成。

- [ ] **Step 5: 檢查工作樹只包含預期檔案**

```powershell
git status --short
git diff --check
```

Expected: 無 whitespace error；不修改後端、API、WebSocket、GPS、相機、採樣服務與模擬 payload 檔案。
