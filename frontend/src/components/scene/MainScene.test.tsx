import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { MainScene } from './MainScene';

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
vi.mock('./Jam', () => ({ Jam: () => null }));
vi.mock('./Tower', () => ({ Tower: () => null }));
vi.mock('./UAVFlight', () => ({
  __esModule: true,
  default: () => null,
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
  useDeviceStore: (selector: (state: { devices: Array<{ role: string }> }) => unknown) =>
    selector({ devices: [] }),
}));

describe('MainScene heatmap overlay', () => {
  it('renders ISS heatmap overlay when provided', () => {
    render(
      <MainScene
        heatmapOverlay={{
          url: '/api/iss-unet/grids/iss_unet_ntpu_ratio_20_reconstructed.npy',
          rows: 128,
          cols: 128,
          areaM: 512,
          opacity: 0.55,
          vminDbm: -90,
          vmaxDbm: -15,
        }}
      />,
    );

    expect(screen.getByTestId('heatmap-overlay')).toHaveTextContent('/api/iss-unet/grids/iss_unet_ntpu_ratio_20_reconstructed.npy');
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
