import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { MainScene } from './MainScene';

const storeState = vi.hoisted(() => ({
  devices: [
    { id: 'tx-1', role: 'tx', x: 1, y: 2, z: 3 },
    { id: 'tx-2', role: 'tx', x: 4, y: 5, z: 6 },
    { id: 'jam-1', role: 'jammer', x: 7, y: 8, z: 9 },
  ],
  modelVisible: { tx: true, rx: true, jammer: true },
}));

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: { children: ReactNode }) => <div data-testid="canvas">{children}</div>,
}));

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
  PerspectiveCamera: () => null,
  Html: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('./NTPUScene', () => ({ NTPUScene: () => null }));
vi.mock('./NYCUScene', () => ({ NYCUScene: () => null }));
vi.mock('./DynamicScene', () => ({ DynamicScene: () => null }));
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
  ISSHeatmapOverlay: ({ overlay }: { overlay: { url: string } }) => (
    <div data-testid="heatmap-overlay">{overlay.url}</div>
  ),
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
});

describe('MainScene device visibility', () => {
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
