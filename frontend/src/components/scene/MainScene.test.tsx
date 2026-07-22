import { useEffect, type ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MainScene } from './MainScene';

const storeState = vi.hoisted(() => ({
  devices: [
    { id: 'tx-1', role: 'tx', x: 1, y: 2, z: 3 },
    { id: 'tx-2', role: 'tx', x: 4, y: 5, z: 6 },
    { id: 'jam-1', role: 'jammer', x: 7, y: 8, z: 9 },
  ],
  modelVisible: { tx: true, rx: true, jammer: true },
}));

const sceneMocks = vi.hoisted(() => ({
  clear: vi.fn(() => {
    sceneMocks.failDynamic = false;
  }),
  dynamicAttempts: 0,
  failDynamic: false,
}));

const canvasMock = vi.hoisted(() => ({
  dpr: undefined as number | [number, number] | undefined,
}));

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children, dpr }: { children: ReactNode; dpr?: number | [number, number] }) => {
    canvasMock.dpr = dpr;
    return <div data-testid="canvas">{children}</div>;
  },
}));

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
  PerspectiveCamera: () => null,
  Html: ({ children }: { children: ReactNode }) => <>{children}</>,
  useGLTF: { clear: sceneMocks.clear },
}));

vi.mock('./NTPUScene', () => ({ NTPUScene: () => null }));
vi.mock('./NYCUScene', () => ({ NYCUScene: () => null }));
vi.mock('./DynamicScene', () => ({
  DynamicScene: () => {
    sceneMocks.dynamicAttempts += 1;
    if (sceneMocks.failDynamic) throw new Error('GLB failed');
    return <div data-testid="dynamic-scene" />;
  },
}));
vi.mock('./UAVPath', () => ({ UAVPath: () => null }));
vi.mock('./UAV', () => ({ UAV: () => null }));
vi.mock('../ui/Starfield', () => ({ Starfield: () => null }));
vi.mock('./Jam', () => ({ Jam: () => <div data-testid="jam-model" /> }));
vi.mock('./Tower', () => ({ Tower: () => <div data-testid="tx-model" /> }));
vi.mock('./UAVFlight', () => ({
  __esModule: true,
  default: ({ visible }: { visible?: boolean }) => (
    <div data-testid="rx-model" data-visible={String(visible)} />
  ),
}));
vi.mock('./CFARBeaconMarker', () => ({ CFARBeaconMarker: () => null }));
vi.mock('./ISSHeatmapOverlay', () => ({
  ISSHeatmapOverlay: ({ overlay, onStatusChange }: { overlay: { url: string }; onStatusChange?: (status: string) => void }) => {
    useEffect(() => onStatusChange?.('ready'), [onStatusChange]);
    return <div data-testid="heatmap-overlay">{overlay.url}</div>;
  },
}));
vi.mock('./ISSRouteOverlay', () => ({
  ISSRouteOverlay: ({ overlay }: { overlay: { routeMode: string } }) => (
    <div data-testid="route-overlay">{overlay.routeMode}</div>
  ),
}));
vi.mock('../../store/useDeviceStore', () => ({
  useDeviceStore: (selector: (state: typeof storeState) => unknown) => selector(storeState),
}));

beforeEach(() => {
  storeState.modelVisible = { tx: true, rx: true, jammer: true };
  sceneMocks.clear.mockClear();
  sceneMocks.dynamicAttempts = 0;
  sceneMocks.failDynamic = false;
});

describe('MainScene device visibility', () => {
  it('caps render density for high-DPI displays', () => {
    render(<MainScene />);

    expect(canvasMock.dpr).toEqual([1, 1.5]);
  });

  it.each([
    ['tx', 'tx-model', 0, 1],
    ['jammer', 'jam-model', 2, 0],
  ] as const)('hides every %s model without hiding other roles', (role, hiddenTestId, txCount, jamCount) => {
    storeState.modelVisible = { tx: true, rx: true, jammer: true, [role]: false };

    render(<MainScene />);

    expect(screen.queryAllByTestId(hiddenTestId)).toHaveLength(0);
    expect(screen.queryAllByTestId('tx-model')).toHaveLength(txCount);
    expect(screen.getByTestId('rx-model')).toHaveAttribute('data-visible', 'true');
    expect(screen.queryAllByTestId('jam-model')).toHaveLength(jamCount);
  });

  it('keeps RX flight mounted while hiding its model', () => {
    storeState.modelVisible.rx = false;

    render(<MainScene />);

    expect(screen.getByTestId('rx-model')).toHaveAttribute('data-visible', 'false');
  });
});

describe('MainScene scene loading', () => {
  it('clears the failed GLB cache and recovers when retried', async () => {
    const user = userEvent.setup();
    sceneMocks.failDynamic = true;
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});

    try {
      render(<MainScene generatedSceneModelPath="/generated/test.glb" />);

      expect(screen.getByRole('alert')).toHaveTextContent('場景載入失敗');
      await user.click(screen.getByRole('button', { name: '重試' }));

      expect(sceneMocks.clear).toHaveBeenCalledWith('/generated/test.glb');
      expect(screen.getByTestId('dynamic-scene')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
  });
});

describe('MainScene heatmap overlay', () => {
  it('renders ISS heatmap overlay when provided', () => {
    render(
      <MainScene
        heatmapOverlay={{
          url: '/api/iss-unet/maps/ntpu/grids/iss_unet_ntpu_ratio_20_reconstructed.npy',
          rows: 128,
          cols: 128,
          areaM: 512,
          opacity: 0.55,
          vminDbm: -90,
          vmaxDbm: -15,
        }}
      />,
    );

    expect(screen.getByTestId('heatmap-overlay')).toHaveTextContent('/api/iss-unet/maps/ntpu/grids/iss_unet_ntpu_ratio_20_reconstructed.npy');
  });

  it('does not render ISS heatmap overlay when absent', () => {
    render(<MainScene />);

    expect(screen.queryByTestId('heatmap-overlay')).not.toBeInTheDocument();
  });

  it('renders ISS route overlay when provided', () => {
    render(
      <MainScene
        issRouteOverlay={{
          routeMode: 'aligned',
          routePoints: [],
          alignedPoints: [],
          samplePoints: [],
        }}
      />,
    );

    expect(screen.getByTestId('route-overlay')).toHaveTextContent('aligned');
  });
});
