import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SimulationPanel } from './SimulationPanel';

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
        reconstructed: '/api/iss-unet/images/reconstructed.png',
        comparison: '/api/iss-unet/images/comparison.png',
        cfar: '/api/iss-unet/images/cfar.png',
      },
      metrics: {
        aligned_noise: 0,
        skipped_noise: 0,
        used_samples: 10,
        sparse_samples: 2,
        route_points: 0,
      },
      options: {
        apply_building_mask: true,
      },
    }),
  } as Response);
}

function successfulStatisticsResponse() {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      images: {
        statistics: '/api/iss-unet/images/iss_unet_ntpu_gps_n_statistics.png',
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

async function openPanel() {
  const user = userEvent.setup();
  render(<SimulationPanel sceneId="NTPU" />);
  await user.click(screen.getByRole('button', { name: /sionna/i }));
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

  it('opens and closes the Sionna simulation panel', async () => {
    const user = await openPanel();

    expect(screen.getByRole('button', { name: 'SINR Map' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /close simulation panel/i }));

    expect(screen.queryByRole('button', { name: 'SINR Map' })).not.toBeInTheDocument();
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

    await user.click(screen.getByRole('button', { name: 'Noise with GPS' }));
    expect(screen.getByText('GPS CSV')).toBeInTheDocument();
    expect(screen.getByText('Noise CSV')).toBeInTheDocument();

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
    expect(form.get('focus_sampling_points')).toBe('true');
    expect(JSON.parse(String(form.get('devices_json')))).toEqual(
      expect.arrayContaining([expect.objectContaining({ role: 'jammer' })]),
    );
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
    await user.click(screen.getByRole('button', { name: 'Noise with GPS' }));
    await user.click(screen.getByRole('button', { name: '產生統計資料' }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/iss-unet/statistics/upload',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
      }),
    ));
    const image = await screen.findByRole('img', { name: 'ISS_UNET GPS_N 統計資料' });
    expect(image).toHaveAttribute('src', expect.stringContaining('/api/iss-unet/images/iss_unet_ntpu_gps_n_statistics.png'));
    expect(screen.queryByRole('link', { name: '下載統計表格' })).not.toBeInTheDocument();

    await user.click(image);

    const dialog = await screen.findByRole('dialog', { name: 'ISS_UNET GPS_N 統計資料' });
    expect(within(dialog).getByRole('img', { name: 'ISS_UNET GPS_N 統計資料' })).toHaveAttribute('src', image.getAttribute('src'));
    expect(within(dialog).getByRole('link', { name: /download/i })).toHaveAttribute('download', 'iss_unet_gpsn_statistics.png');
  });
});
