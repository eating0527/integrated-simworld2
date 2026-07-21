import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SimulationPanel } from './SimulationPanel';

const testFrame = {
  frame_id: 'scene-test',
  origin: { lat: 24, lon: 121, alt_m: 0 },
  alt_mode: 'amsl' as const,
  extent: { min_e: -256, max_e: 256, min_n: -256, max_n: 256 },
  display_margin_m: 32,
  grid: { rows: 128, cols: 128, pixel_size_e_m: 4, pixel_size_n_m: 4 },
};

function routePoint(east: number, north: number, up: number, extra: Record<string, unknown> = {}) {
  return {
    lat: 24,
    lon: 121,
    alt: up,
    alt_mode: 'relative' as const,
    frame_id: 'scene-test',
    enu: { east_m: east, north_m: north, up_m: up },
    grid: { row: 64, col: 64, inside_extent: true, displayable: true },
    ...extra,
  };
}

function successfulPngResponse() {
  return Promise.resolve({
    ok: true,
    blob: () => Promise.resolve(new Blob(['png'], { type: 'image/png' })),
  } as Response);
}

function successfulIssUnetResponse() {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      sparse_ratio: 0.2,
      mode: 'sim',
      images: {
        reconstructed: '/api/iss-unet/maps/ntpu/reconstructed.png',
        comparison: '/api/iss-unet/maps/ntpu/comparison.png',
        cfar: '/api/iss-unet/maps/ntpu/cfar.png',
      },
      metrics: {
        aligned_noise: 0,
        skipped_noise: 0,
        used_samples: 10,
        sparse_samples: 2,
        route_points: 2,
      },
      route: {
        all_points: [
          routePoint(2, 2, 1),
          routePoint(6, 6, 2),
        ],
        aligned_points: [
          routePoint(2, 2, 1, { noise_floor_db: -80 }),
        ],
        sparse_points: [routePoint(2, 2, 1, { noise_floor_db: -80, used_in_sparse: true })],
      },
      overlay: {
        kind: 'reconstructed_iss',
        url: '/api/iss-unet/maps/ntpu/grids/iss_unet_ntpu_ratio_20_reconstructed.npy',
        rows: 128,
        cols: 128,
        area_m: 512,
        frame_id: 'scene-test',
        frame: testFrame,
        grid: { rows: 128, cols: 128, pixel_size_e_m: 4, pixel_size_n_m: 4 },
        vmin_dbm: -90,
        vmax_dbm: -15,
      },
      options: {
        apply_building_mask: true,
      },
      cfar: {
        grid: {
          rows: 128,
          cols: 128,
          area_m: 512,
          pixel_size_m: 4,
        },
        detections: 1,
        clusters: [
          {
            peak_pixel_row: 64,
            peak_pixel_col: 64,
            peak_power_dbm: -42.5,
            mean_power_dbm: -45,
            size: 9,
            frame_id: 'scene-test',
            enu: { east_m: 2, north_m: 2, up_m: 0 },
            grid: { row: 64, col: 64, inside_extent: true, displayable: true },
            lat: 24,
            lon: 121,
            alt: 0,
            alt_mode: 'amsl',
          },
        ],
      },
    }),
  } as Response);
}

function successfulIssUnetResponseWithoutRoute() {
  return successfulIssUnetResponse().then(async response => ({
    ...response,
    json: async () => {
      const json = await response.json();
      delete json.route;
      return json;
    },
  } as Response));
}

function successfulIssUnetResponseWithEmptyRoute() {
  return successfulIssUnetResponse().then(async response => ({
    ...response,
    json: async () => {
      const json = await response.json();
      json.route = {
        all_points: [],
        aligned_points: [],
        sparse_points: [],
      };
      return json;
    },
  } as Response));
}

function successfulStatisticsResponse() {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      images: {
        statistics: '/api/iss-unet/maps/ntpu/iss_unet_ntpu_gps_n_statistics.png',
      },
      statistics: {
        rows: [
          { variable: '採樣點地圖覆蓋率', value: '0.01%', meaning: '採樣點覆蓋整張室外地圖的比例' },
        ],
      },
    }),
  } as Response);
}

function failedJsonResponse(message: string) {
  return Promise.resolve({
    ok: false,
    json: () => Promise.resolve({ detail: message }),
  } as Response);
}

function deferredPngResponse() {
  let resolveResponse!: (response: Response) => void;
  const response = new Promise<Response>((resolve) => {
    resolveResponse = resolve;
  });
  return {
    response,
    resolve: () => resolveResponse({
      ok: true,
      blob: () => Promise.resolve(new Blob(['png'], { type: 'image/png' })),
    } as Response),
  };
}

async function restorePanel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Restore 無線通道模擬' }));
}

async function openPanel() {
  const user = userEvent.setup();
  render(<SimulationPanel sceneId="NTPU" />);
  await restorePanel(user);
  return user;
}

async function runCurrentTab(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /run simulation/i }));
}

function lastFetchJsonBody() {
  const fetchMock = vi.mocked(globalThis.fetch);
  const [, init] = fetchMock.mock.calls.at(-1) ?? [];
  return JSON.parse(String((init as RequestInit).body));
}

describe('SimulationPanel UI', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => successfulPngResponse()));
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:simulation-result'),
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('starts minimized and restores the simulation panel on demand', async () => {
    const user = userEvent.setup();
    render(<SimulationPanel sceneId="NTPU" />);

    expect(screen.queryByRole('button', { name: 'SINR Map' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Restore 無線通道模擬' }));

    expect(screen.getByRole('button', { name: 'SINR Map' })).toBeInTheDocument();
  });

  it('switches tabs and shows CFR advanced controls', async () => {
    const user = await openPanel();

    await user.click(screen.getByRole('button', { name: 'CFR' }));
    await user.click(screen.getByRole('button', { name: /cfr advanced/i }));

    expect(screen.getByLabelText('Modulation')).toHaveValue('qpsk');
    expect(screen.getByText('Constellation Batch Size')).toBeInTheDocument();
    expect(screen.getByLabelText('OFDM Subcarriers')).toHaveValue('76');
    expect(screen.getByLabelText('Ray Tracing Max Depth')).toHaveValue('10');
  });

  it('submits SINR request with edited numeric parameters', async () => {
    const user = await openPanel();

    fireEvent.change(screen.getByLabelText('SINR Min (dB)'), { target: { value: '-30' } });
    fireEvent.change(screen.getByLabelText('SINR Max (dB)'), { target: { value: '50' } });
    fireEvent.change(screen.getByLabelText('Cell Size (m)'), { target: { value: '4' } });
    await user.selectOptions(screen.getByLabelText('Samples / TX'), '1000000');

    await runCurrentTab(user);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sionna/sinr-map',
      expect.any(Object),
    ));
    expect(lastFetchJsonBody()).toMatchObject({
      scene: 'NTPU',
      sinr_vmin: -30,
      sinr_vmax: 50,
      cell_size: 4,
      samples_per_tx: 1000000,
    });
  });

  it('submits CFR request with modulation and advanced parameters', async () => {
    const user = await openPanel();

    await user.click(screen.getByRole('button', { name: 'CFR' }));
    await user.selectOptions(screen.getByLabelText('Modulation'), '16qam');
    await user.click(screen.getByRole('button', { name: /cfr advanced/i }));
    await user.selectOptions(screen.getByLabelText('Constellation Batch Size'), '10');
    await user.selectOptions(screen.getByLabelText('OFDM Subcarriers'), '128');
    fireEvent.change(screen.getByLabelText('Subcarrier Spacing (kHz)'), { target: { value: '60' } });
    fireEvent.change(screen.getByLabelText('Eb/N0'), { target: { value: '18' } });
    await user.selectOptions(screen.getByLabelText('Ray Tracing Max Depth'), '3');

    await runCurrentTab(user);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/sionna/cfr-plot',
      expect.any(Object),
    ));
    expect(lastFetchJsonBody()).toMatchObject({
      scene: 'NTPU',
      modulation: '16qam',
      advanced: {
        constellation_batch_size: 10,
        ofdm_subcarriers: 128,
        subcarrier_spacing_hz: 60000,
        ebn0_db: 18,
        ray_tracing_max_depth: 3,
      },
    });
  });

  it('submits ISS, TSS, and CFAR requests with the selected map type', async () => {
    const user = await openPanel();

    for (const [tabName, mapType] of [
      ['ISS Map', 'iss'],
      ['TSS Map', 'tss'],
      ['ISS+CFAR Map', 'cfar'],
    ] as const) {
      await user.click(screen.getByRole('button', { name: tabName }));
      await runCurrentTab(user);

      await waitFor(() => expect(globalThis.fetch).toHaveBeenLastCalledWith(
        '/api/simulate',
        expect.any(Object),
      ));
      expect(lastFetchJsonBody()).toMatchObject({
        scene: 'NTPU',
        map_type: mapType,
      });
    }
  });

  it('submits ISS_UNET sim and upload modes to the correct endpoints', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponse());
    const user = await openPanel();

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await runCurrentTab(user);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/iss-unet/reconstruct',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }),
    ));
    expect(lastFetchJsonBody()).toMatchObject({
      scene: 'NTPU',
      sparse_ratio: 0.2,
      cfar: { enabled: true },
    });

    await user.click(screen.getByRole('button', { name: 'Noise + GPS' }));
    expect(screen.getByText('GPS CSV')).toBeInTheDocument();
    expect(screen.getByText('Noise CSV')).toBeInTheDocument();
    const noiseFilter = screen.getByRole('checkbox', { name: 'Noise Filter (>= -1 dB)' });
    expect(noiseFilter).toBeChecked();
    expect(screen.queryByLabelText('Focus Sampling Points')).not.toBeInTheDocument();

    await user.click(noiseFilter);
    expect(noiseFilter).not.toBeChecked();

    await runCurrentTab(user);

    await waitFor(() => expect(globalThis.fetch).toHaveBeenLastCalledWith(
      '/api/iss-unet/reconstruct/upload',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
      }),
    ));
    const [, init] = vi.mocked(globalThis.fetch).mock.calls.at(-1) ?? [];
    const form = (init as RequestInit).body as FormData;
    expect(form.get('mode')).toBe('gps_n');
    expect(form.get('filter_noise')).toBe('false');
    expect(form.get('focus_sampling_points')).toBeNull();
    expect(JSON.parse(String(form.get('devices_json')))).toEqual(
      expect.arrayContaining([expect.objectContaining({ role: 'jammer' })]),
    );
  });

  it('shows GPS replay controls for ISS_UNET upload modes', async () => {
    const onGpsReplayRateChange = vi.fn();
    const user = userEvent.setup();
    function Harness() {
      const [rate, setRate] = useState<1 | 2 | 5>(1);
      return (
        <SimulationPanel
          sceneId="NTPU"
          gpsReplayRate={rate}
          onGpsReplayRateChange={(nextRate) => {
            onGpsReplayRateChange(nextRate);
            setRate(nextRate);
          }}
        />
      );
    }
    render(<Harness />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    expect(screen.queryByRole('button', { name: 'GPS replay play' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'GPS' }));

    expect(screen.getByRole('button', { name: 'GPS replay play' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'GPS replay pause' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'GPS replay stop' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'GPS replay rate' }));
    await user.click(screen.getByRole('button', { name: 'GPS replay rate' }));

    expect(onGpsReplayRateChange).toHaveBeenNthCalledWith(1, 2);
    expect(onGpsReplayRateChange).toHaveBeenNthCalledWith(2, 5);
  });

  it('publishes CFAR clusters from ISS_UNET results for scene beacon rendering', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponse());
    const onCfarClustersChange = vi.fn();
    const user = userEvent.setup();
    render(<SimulationPanel sceneId="NTPU" onCfarClustersChange={onCfarClustersChange} />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await runCurrentTab(user);

    await waitFor(() => expect(onCfarClustersChange).toHaveBeenCalledWith([
      expect.objectContaining({
        peak_pixel_row: 64,
        peak_pixel_col: 64,
        peak_power_dbm: -42.5,
        enu: { east_m: 2, north_m: 2, up_m: 0 },
      }),
    ]));
  });

  it('does not enable 3D heatmap overlay until the user turns it on', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponse());
    const onHeatmapOverlayChange = vi.fn();
    const user = userEvent.setup();
    render(<SimulationPanel sceneId="NTPU" onHeatmapOverlayChange={onHeatmapOverlayChange} />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await runCurrentTab(user);

    await screen.findByRole('checkbox', { name: '3D Heatmap Overlay' });
    expect(onHeatmapOverlayChange).not.toHaveBeenCalledWith(
      expect.objectContaining({
        url: expect.stringContaining('/api/iss-unet/maps/ntpu/grids/iss_unet_ntpu_ratio_20_reconstructed.npy'),
      }),
    );
  });

  it('publishes heatmap overlay state when toggled and opacity changes', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponse());
    const onHeatmapOverlayChange = vi.fn();
    const user = userEvent.setup();
    render(<SimulationPanel sceneId="NTPU" onHeatmapOverlayChange={onHeatmapOverlayChange} />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await runCurrentTab(user);

    await user.click(await screen.findByRole('checkbox', { name: '3D Heatmap Overlay' }));

    await waitFor(() => expect(onHeatmapOverlayChange).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/api/iss-unet/maps/ntpu/grids/iss_unet_ntpu_ratio_20_reconstructed.npy',
        opacity: 0.55,
        rows: 128,
        cols: 128,
        areaM: 512,
      }),
    ));

    fireEvent.change(screen.getByLabelText('Overlay Opacity'), { target: { value: '0.8' } });

    await waitFor(() => expect(onHeatmapOverlayChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        opacity: 0.8,
      }),
    ));
  });

  it('publishes ISS route overlay and switches route display mode', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponse());
    const onRouteOverlayChange = vi.fn();
    const user = userEvent.setup();
    render(<SimulationPanel sceneId="NTPU" onRouteOverlayChange={onRouteOverlayChange} />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await user.click(screen.getByRole('button', { name: 'Noise + GPS' }));
    await runCurrentTab(user);

    await waitFor(() => expect(onRouteOverlayChange).toHaveBeenCalledWith(
      expect.objectContaining({
        routeMode: 'all',
        routePoints: expect.arrayContaining([expect.objectContaining({ enu: { east_m: 2, north_m: 2, up_m: 1 } })]),
        samplePoints: expect.arrayContaining([expect.objectContaining({ noise_floor_db: -80 })]),
      }),
    ));

    await user.click(screen.getByRole('button', { name: 'Aligned only' }));

    await waitFor(() => expect(onRouteOverlayChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        routeMode: 'aligned',
        alignedPoints: expect.arrayContaining([expect.objectContaining({ enu: { east_m: 2, north_m: 2, up_m: 1 } })]),
      }),
    ));
  });

  it('does not publish a non-null ISS_UNET route overlay without route data', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponseWithoutRoute());
    const onRouteOverlayChange = vi.fn();
    const user = userEvent.setup();
    render(<SimulationPanel sceneId="NTPU" onRouteOverlayChange={onRouteOverlayChange} />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await runCurrentTab(user);

    await screen.findByRole('checkbox', { name: '3D Heatmap Overlay' });
    expect(screen.queryByText('3D Route')).not.toBeInTheDocument();
    expect(onRouteOverlayChange).not.toHaveBeenCalledWith(expect.objectContaining({
      routeMode: expect.any(String),
    }));
  });

  it('does not publish a non-null ISS_UNET route overlay when route arrays are empty', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponseWithEmptyRoute());
    const onRouteOverlayChange = vi.fn();
    const user = userEvent.setup();
    render(<SimulationPanel sceneId="NTPU" onRouteOverlayChange={onRouteOverlayChange} />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await runCurrentTab(user);

    await screen.findByRole('checkbox', { name: '3D Heatmap Overlay' });
    expect(screen.queryByText('3D Route')).not.toBeInTheDocument();
    expect(onRouteOverlayChange).not.toHaveBeenCalledWith(expect.objectContaining({
      routeMode: expect.any(String),
    }));
  });

  it('clears a previously enabled heatmap overlay on rerun and scene change', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulIssUnetResponse());
    const onHeatmapOverlayChange = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<SimulationPanel sceneId="NTPU" onHeatmapOverlayChange={onHeatmapOverlayChange} />);
    await restorePanel(user);

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await runCurrentTab(user);
    await user.click(await screen.findByRole('checkbox', { name: '3D Heatmap Overlay' }));

    await waitFor(() => expect(onHeatmapOverlayChange).toHaveBeenCalledWith(
      expect.objectContaining({
        url: '/api/iss-unet/maps/ntpu/grids/iss_unet_ntpu_ratio_20_reconstructed.npy',
      }),
    ));

    await runCurrentTab(user);
    await waitFor(() => expect(onHeatmapOverlayChange).toHaveBeenLastCalledWith(null));

    rerender(<SimulationPanel sceneId="NYCU" onHeatmapOverlayChange={onHeatmapOverlayChange} />);
    await waitFor(() => expect(onHeatmapOverlayChange).toHaveBeenLastCalledWith(null));
  });

  it('shows loading state while a simulation request is pending', async () => {
    const pending = deferredPngResponse();
    vi.mocked(globalThis.fetch).mockImplementation(() => pending.response);
    const user = await openPanel();

    await runCurrentTab(user);

    await waitFor(() => expect(screen.getByRole('button', { name: /run simulation/i })).toBeDisabled());

    pending.resolve();
    await waitFor(() => expect(screen.getByRole('button', { name: /run simulation/i })).not.toBeDisabled());
  });

  it('renders an image result after a successful response', async () => {
    const user = await openPanel();

    await runCurrentTab(user);

    const image = await screen.findByRole('img', { name: 'sinr' });
    expect(image).toHaveAttribute('src', 'blob:simulation-result');
  });

  it('renders backend error messages', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => failedJsonResponse('Sionna failed'));
    const user = await openPanel();

    await runCurrentTab(user);

    expect(await screen.findByRole('alert')).toHaveTextContent('Sionna failed');
  });

  it('opens and closes the image preview modal', async () => {
    const user = await openPanel();

    await runCurrentTab(user);
    await user.click(await screen.findByRole('img', { name: 'sinr' }));

    const dialog = await screen.findByRole('dialog', { name: 'SINR' });
    expect(within(dialog).getByRole('img', { name: 'SINR' })).toHaveAttribute('src', 'blob:simulation-result');
    expect(within(dialog).getByRole('link', { name: /download/i })).toHaveAttribute('href', 'blob:simulation-result');

    fireEvent.click(dialog.parentElement as HTMLElement);

    expect(screen.queryByRole('dialog', { name: 'SINR' })).not.toBeInTheDocument();
  });

  it('generates and displays downloadable gps_n statistics table', async () => {
    vi.mocked(globalThis.fetch).mockImplementation(() => successfulStatisticsResponse());
    const user = await openPanel();

    await user.click(screen.getByRole('button', { name: 'ISS_UNET' }));
    await user.click(screen.getByRole('button', { name: 'Noise + GPS' }));
    await user.click(screen.getByRole('button', { name: '產生統計資料' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/iss-unet/statistics/upload',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
      }),
    ));
    const image = await screen.findByRole('img', { name: 'ISS_UNET GPS_N 統計資料' });
    expect(image).toHaveAttribute('src', expect.stringContaining('/api/iss-unet/maps/ntpu/iss_unet_ntpu_gps_n_statistics.png'));
    expect(screen.queryByRole('link', { name: '下載統計表格' })).not.toBeInTheDocument();

    await user.click(image);

    const dialog = await screen.findByRole('dialog', { name: 'ISS_UNET GPS_N 統計資料' });
    expect(within(dialog).getByRole('img', { name: 'ISS_UNET GPS_N 統計資料' })).toHaveAttribute('src', image.getAttribute('src'));
    expect(within(dialog).getByRole('link', { name: /download/i })).toHaveAttribute('download', 'iss_unet_gpsn_statistics.png');
  });
});
