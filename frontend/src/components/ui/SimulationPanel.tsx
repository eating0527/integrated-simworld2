import { useState, useCallback } from 'react';
import { useEffect } from 'react';
import { getCurrentDevicePayload } from '../../utils/devicePayload';
import { buildIssUnetSimRequestBody, buildIssUnetUploadFormData } from '../../utils/issUnetRequest';

const API = import.meta.env.VITE_API_URL || '';

type TabKey = 'sinr' | 'cfr' | 'doppler' | 'channel' | 'iss' | 'tss' | 'cfar' | 'iss_unet';
type CFRModulation = 'qpsk' | '16qam';
type ComputeImpact = 'low' | 'medium' | 'high';
type ISSUNetMode = 'sim' | 'gps' | 'gps_n';

interface CFRAdvancedParams {
  constellationBatchSize: number;
  ofdmSubcarriers: number;
  subcarrierSpacingHz: number;
  ebn0Db: number;
  rayTracingMaxDepth: number;
}

interface SINRParams {
  sinr_vmin: number;
  sinr_vmax: number;
  cell_size: number;
  samples_per_tx: number;
}

interface ISSUNetParams {
  mode: ISSUNetMode;
  sparseRatioPercent: number;
  cfar_enabled: boolean;
  apply_building_mask: boolean;
  focusSamplingPoints: boolean;
  gpsFile: File | null;
  noiseFile: File | null;
}

type ISSUNetViewKey = 'reconstructed' | 'comparison' | 'cfar';

interface ISSUNetImages {
  reconstructed: string | null;
  comparison: string | null;
  cfar: string | null;
}

const ISS_UNET_VIEW_LABELS: Record<ISSUNetViewKey, string> = {
  reconstructed: 'Reconstructed',
  comparison: '干擾地圖',
  cfar: 'CFAR',
};

interface SimStatus {
  loading: boolean;
  imageUrl: string | null;
  error: string | null;
  metrics?: Record<string, unknown> | null;
  options?: Record<string, unknown> | null;
  issUnetImages?: ISSUNetImages | null;
}

const EMPTY: SimStatus = { loading: false, imageUrl: null, error: null, metrics: null, options: null, issUnetImages: null };
const GENERATED_SCENE_TABS: TabKey[] = ['sinr', 'cfr', 'doppler', 'channel', 'iss', 'tss', 'cfar', 'iss_unet'];
const DEFAULT_CFR_ADVANCED: CFRAdvancedParams = {
  constellationBatchSize: 1,
  ofdmSubcarriers: 76,
  subcarrierSpacingHz: 30000,
  ebn0Db: 20,
  rayTracingMaxDepth: 10,
};
const ISS_UNET_MODE_LABELS: Record<ISSUNetMode, string> = {
  sim: 'Sim',
  gps: 'GPS',
  gps_n: 'Noise with GPS',
};

interface SimulationPanelProps {
  sceneId?: string | null;
  generatedScene?: boolean;
}

export function SimulationPanel({ sceneId = 'NTPU', generatedScene = false }: SimulationPanelProps) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<TabKey>('sinr');
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(null);
  const [issUnetActiveView, setIssUnetActiveView] = useState<ISSUNetViewKey>('comparison');
  const [overlayScene, setOverlayScene] = useState(false);
  const [cfrModulation, setCfrModulation] = useState<CFRModulation>('qpsk');
  const [cfrAdvancedOpen, setCfrAdvancedOpen] = useState(false);
  const [cfrAdvanced, setCfrAdvanced] = useState<CFRAdvancedParams>(DEFAULT_CFR_ADVANCED);
  const [status, setStatus] = useState<Record<TabKey, SimStatus>>({
    sinr:    { ...EMPTY },
    cfr:     { ...EMPTY },
    doppler: { ...EMPTY },
    channel: { ...EMPTY },
    iss:     { ...EMPTY },
    tss:     { ...EMPTY },
    cfar:    { ...EMPTY },
    iss_unet:{ ...EMPTY },
  });

  const [sinrParams, setSinrParams] = useState<SINRParams>({
    sinr_vmin: -20,
    sinr_vmax: 40,
    cell_size: 3.0,
    samples_per_tx: 100000000,
  });
  const [issUnetParams, setIssUnetParams] = useState<ISSUNetParams>({
    mode: 'sim',
    sparseRatioPercent: 20,
    cfar_enabled: true,
    apply_building_mask: true,
    focusSamplingPoints: true,
    gpsFile: null,
    noiseFile: null,
  });

  useEffect(() => {
    if (generatedScene && !GENERATED_SCENE_TABS.includes(tab)) {
      setTab('iss');
    }
  }, [generatedScene, tab]);

  const updateCfrAdvanced = <K extends keyof CFRAdvancedParams>(
    key: K,
    value: CFRAdvancedParams[K],
  ) => {
    setCfrAdvanced(prev => ({ ...prev, [key]: value }));
  };

  const compute = useCallback(async (key: TabKey) => {
    if (generatedScene && !sceneId) {
      setStatus(prev => ({
        ...prev,
        [key]: {
          loading: false,
          imageUrl: null,
          error: 'Picked generated scene has no Sionna scene key. Regenerate the scene before running simulation.',
        },
      }));
      return;
    }

      setStatus(prev => ({ ...prev, [key]: { loading: true, imageUrl: null, error: null, metrics: null, options: null } }));

    try {
      let res;
      const requestSceneId = sceneId ?? 'NTPU';
      const devicePayload = getCurrentDevicePayload();

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
      } else if (key === 'iss_unet') {
        if (issUnetParams.mode === 'sim') {
          res = await fetch(`${API}/api/iss-unet/reconstruct`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(buildIssUnetSimRequestBody({
              scene: requestSceneId,
              sparseRatioPercent: issUnetParams.sparseRatioPercent,
              cfarEnabled: issUnetParams.cfar_enabled,
              applyBuildingMask: issUnetParams.apply_building_mask,
              focusSamplingPoints: issUnetParams.focusSamplingPoints,
              devices: devicePayload,
            })),
          });
        } else {
          const form = buildIssUnetUploadFormData({
            scene: requestSceneId,
            mode: issUnetParams.mode,
            sparseRatioPercent: issUnetParams.sparseRatioPercent,
            cfarEnabled: issUnetParams.cfar_enabled,
            applyBuildingMask: issUnetParams.apply_building_mask,
            focusSamplingPoints: issUnetParams.focusSamplingPoints,
            gpsFile: issUnetParams.gpsFile,
            noiseFile: issUnetParams.noiseFile,
            devices: devicePayload,
          });
          res = await fetch(`${API}/api/iss-unet/reconstruct/upload`, {
            method: 'POST',
            body: form,
          });
        }
      } else if (['iss', 'tss', 'cfar'].includes(key)) {
        res = await fetch(`${API}/api/simulate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scene: requestSceneId,
            map_type: key,
            cell_size: sinrParams.cell_size,
            samples_per_tx: sinrParams.samples_per_tx,
            sinr_vmin: sinrParams.sinr_vmin,
            sinr_vmax: sinrParams.sinr_vmax,
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

      if (!res || !res.ok) {
        const json = res ? await res.json().catch(() => ({ error: 'HTTP Error' })) : { error: 'Unknown Error' };
        const missing = Array.isArray(json.missing_files) ? `: ${json.missing_files.join(', ')}` : '';
        throw new Error(`${json.detail || json.error || 'HTTP Error'}${missing}`);
      }

      let url: string;
      if (key === 'iss_unet') {
        const json = await res.json();
        const sparseRatioPercent = typeof json.sparse_ratio === 'number'
          ? json.sparse_ratio * 100
          : issUnetParams.sparseRatioPercent;
        const cacheParams = new URLSearchParams({
          ratio: String(sparseRatioPercent),
          mode: json.mode || issUnetParams.mode,
          t: String(Date.now()),
        });
        const cacheSuffix = cacheParams.toString();
        const buildUrl = (path: string | null) =>
          path ? `${API}${path}?${cacheSuffix}` : null;
        const unetImages: ISSUNetImages = {
          reconstructed: buildUrl(json.images?.reconstructed ?? null),
          comparison: buildUrl(json.images?.comparison ?? null),
          cfar: buildUrl(json.images?.cfar ?? null),
        };
        url = unetImages.comparison || unetImages.reconstructed || '';
        setStatus(prev => ({
          ...prev,
          [key]: {
            loading: false,
            imageUrl: url,
            error: null,
            metrics: json.metrics ?? null,
            options: json.options ?? null,
            issUnetImages: unetImages,
          },
        }));
        return;
      } else {
        const blob = await res.blob();
        url = URL.createObjectURL(blob);
      }
      setStatus(prev => ({ ...prev, [key]: { loading: false, imageUrl: url, error: null, metrics: null, options: null } }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatus(prev => ({ ...prev, [key]: { loading: false, imageUrl: null, error: msg, metrics: null, options: null } }));
    }
  }, [sinrParams, sceneId, overlayScene, generatedScene, cfrModulation, cfrAdvanced, issUnetParams]);

  const cur = status[tab];

  return (
    <>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          position:    'fixed',
          bottom:       14,
          right:        14,
          zIndex:       1000,
          background:   open
            ? 'linear-gradient(135deg, #0ff 0%, #09f 100%)'
            : 'linear-gradient(135deg, rgba(0,255,255,.15) 0%, rgba(0,153,255,.2) 100%)',
          border:       '1px solid rgba(0,255,255,.4)',
          borderRadius: 12,
          padding:      '8px 14px',
          color:        open ? '#000' : '#0ff',
          fontWeight:   700,
          fontSize:     13,
          cursor:       'pointer',
          backdropFilter: 'blur(12px)',
          boxShadow:    '0 4px 20px rgba(0,255,255,.2)',
          transition:   'all .2s',
          letterSpacing: '.5px',
        }}
      >
        📡 無線模擬
      </button>

      {open && (
        <div style={{
          position:       'fixed',
          bottom:          60,
          right:           14,
          zIndex:          999,
          width:           440,
          maxHeight:       '80vh',
          display:         'flex',
          flexDirection:   'column',
          background:      'rgba(10,15,30,.82)',
          backdropFilter:  'blur(20px) saturate(180%)',
          border:          '1px solid rgba(0,255,255,.18)',
          borderRadius:    16,
          boxShadow:       '0 8px 40px rgba(0,255,255,.12), 0 2px 8px rgba(0,0,0,.5)',
          overflow:        'hidden',
          animation:       'slide-in-left .25s ease',
        }}>

          <div style={{ padding: '12px 16px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: '#0ff', fontSize: 13, fontWeight: 700, letterSpacing: 1, flex: 1 }}>
              SIONNA 無線通道模擬
            </span>
            <button
              onClick={() => setOpen(false)}
              style={{
                background: 'none', border: 'none', color: 'rgba(255,255,255,.45)',
                cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 2,
              }}
            >×</button>
          </div>

          {/* 頁籤 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, padding: '10px 12px 0', flexShrink: 0 }}>
            {([
              { key: 'sinr',    label: 'SINR Map' },
              { key: 'cfr',     label: 'CFR' },
              { key: 'doppler', label: 'Doppler' },
              { key: 'channel', label: 'Channel IR' },
              { key: 'iss',     label: 'ISS Map' },
              { key: 'tss',     label: 'TSS Map' },
              { key: 'cfar',    label: 'ISS+CFAR Map' },
              { key: 'iss_unet', label: 'ISS_UNET' },
            ] as { key: TabKey; label: string }[]).map(({ key, label }) => {
              const disabled = generatedScene && !GENERATED_SCENE_TABS.includes(key);
              return (
              <button
                key={key}
                onClick={() => setTab(key)}
                disabled={disabled}
                style={{
                  flex:         '1 1 20%',
                  padding:      '5px 4px',
                  background:   tab === key
                    ? 'linear-gradient(135deg,rgba(0,255,255,.25),rgba(0,153,255,.25))'
                    : 'rgba(255,255,255,.04)',
                  border:       tab === key
                    ? '1px solid rgba(0,255,255,.5)'
                    : '1px solid rgba(255,255,255,.08)',
                  borderRadius: 8,
                  color:        disabled
                    ? 'rgba(255,255,255,.22)'
                    : (tab === key ? '#0ff' : 'rgba(255,255,255,.5)'),
                  fontSize:     11,
                  fontWeight:   tab === key ? 700 : 400,
                  cursor:       disabled ? 'not-allowed' : 'pointer',
                  transition:   'all .15s',
                  whiteSpace:   'nowrap',
                }}
              >
                {label}
              </button>
              );
            })}
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px 16px' }}>
            {/* SINR 或 ISS/TSS/CFAR 專屬參數 */}
            {['sinr', 'iss', 'tss', 'cfar'].includes(tab) && (
              <div style={{ marginBottom: 12 }}>
                <ParamGrid>
                  {tab === 'sinr' && (
                    <>
                      <Label>SINR Min (dB)</Label>
                      <NumberInput
                        value={sinrParams.sinr_vmin}
                        step={5} min={-60} max={0}
                        onChange={v => setSinrParams(p => ({ ...p, sinr_vmin: v }))}
                      />
                      <Label>SINR Max (dB)</Label>
                      <NumberInput
                        value={sinrParams.sinr_vmax}
                        step={5} min={0} max={80}
                        onChange={v => setSinrParams(p => ({ ...p, sinr_vmax: v }))}
                      />
                    </>
                  )}
                  <Label>Cell Size (m)</Label>
                  <NumberInput
                    value={sinrParams.cell_size}
                    step={0.5} min={0.5} max={10}
                    onChange={v => setSinrParams(p => ({ ...p, cell_size: v }))}
                  />
                  <Label>Samples / TX</Label>
                  <select
                    value={sinrParams.samples_per_tx}
                    onChange={e => setSinrParams(p => ({ ...p, samples_per_tx: Number(e.target.value) }))}
                    style={selectStyle}
                  >
                    <option value={500000}>500K (less)</option>
                    <option value={1000000}>1M (medium)</option>
                    <option value={100000000}>100M (recommend)</option>
                    <option value={1000000000}>1B (more)</option>
                  </select>
                  {['sinr', 'iss', 'tss', 'cfar'].includes(tab) && (
                    <>
                      <Label>場景輪廓</Label>
                      <ToggleSwitch checked={overlayScene} onChange={setOverlayScene} />
                    </>
                  )}
                </ParamGrid>
              </div>
            )}

            {tab === 'iss_unet' && (
              <div style={{ marginBottom: 12 }}>
                <ParamGrid>
                  <Label>Sparse Ratio (%)</Label>
                  <NumberInput
                    value={issUnetParams.sparseRatioPercent}
                    step={10} min={0} max={100}
                    disabled={issUnetParams.mode !== 'sim'}
                    onChange={v => setIssUnetParams(p => ({ ...p, sparseRatioPercent: clampNumber(v, 0, 100) }))}
                  />
                  <Label>Mode</Label>
                  <SegmentedControl
                    value={issUnetParams.mode}
                    options={[
                      { value: 'sim', label: 'Sim' },
                      { value: 'gps', label: 'GPS' },
                      { value: 'gps_n', label: 'Noise with GPS' },
                    ]}
                    onChange={mode => setIssUnetParams(p => ({ ...p, mode }))}
                  />
                  {issUnetParams.mode !== 'sim' && (
                    <>
                      <Label>GPS CSV</Label>
                      <FileInput
                        accept=".csv,text/csv"
                        file={issUnetParams.gpsFile}
                        onChange={file => setIssUnetParams(p => ({ ...p, gpsFile: file }))}
                      />
                      <div />
                      <Hint></Hint>
                    </>
                  )}
                  {issUnetParams.mode === 'gps_n' && (
                    <>
                      <Label>Noise CSV</Label>
                      <FileInput
                        accept=".csv,text/csv"
                        file={issUnetParams.noiseFile}
                        onChange={file => setIssUnetParams(p => ({ ...p, noiseFile: file }))}
                      />
                      <div />
                      <Hint>Noise 會依據時間序與 GPS 採樣點對齊。</Hint>
                    </>
                  )}
                  <Label>OS-CFAR</Label>
                  <ToggleSwitch
                    checked={issUnetParams.cfar_enabled}
                    onChange={v => setIssUnetParams(p => ({ ...p, cfar_enabled: v }))}
                  />
                  <div />
                  <Hint>預測並標示干擾源位置。</Hint>
                  <Label>Building Mask</Label>
                  <ToggleSwitch
                    checked={issUnetParams.apply_building_mask}
                    onChange={v => setIssUnetParams(p => ({ ...p, apply_building_mask: v }))}
                  />
                  <div />
                  <Hint>顯示建築物的遮蔽效果。</Hint>
                  <Label>聚焦採樣點</Label>
                  <ToggleSwitch
                    checked={issUnetParams.focusSamplingPoints}
                    disabled={issUnetParams.mode !== 'gps_n'}
                    onChange={v => setIssUnetParams(p => ({ ...p, focusSamplingPoints: v }))}
                  />
                  <div />
                  <Hint>僅 Noise with GPS 模式可用。聚焦 GPS 採樣點周遭的像素（若顯示異常請關閉）。</Hint>
                </ParamGrid>
              </div>
            )}

            {tab === 'cfr' && (
              <div style={{ marginBottom: 12 }}>
                <ParamGrid>
                  <Label>調變方式</Label>
                  <select
                    value={cfrModulation}
                    onChange={e => setCfrModulation(e.target.value as CFRModulation)}
                    style={selectStyle}
                  >
                    <option value="qpsk">QPSK</option>
                    <option value="16qam">16QAM</option>
                  </select>
                </ParamGrid>

                <button
                  type="button"
                  onClick={() => setCfrAdvancedOpen(v => !v)}
                  aria-expanded={cfrAdvancedOpen}
                  aria-controls="cfr-advanced-panel"
                  style={{
                    width: '100%',
                    marginTop: 8,
                    padding: '7px 10px',
                    background: 'rgba(255,255,255,.045)',
                    border: '1px solid rgba(255,255,255,.1)',
                    borderRadius: 8,
                    color: 'rgba(255,255,255,.68)',
                    fontSize: 12,
                    fontWeight: 700,
                    cursor: 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <span>進階設定</span>
                  <span>{cfrAdvancedOpen ? '收合' : '展開'}</span>
                </button>

                {cfrAdvancedOpen && (
                  <div id="cfr-advanced-panel" style={{
                    marginTop: 8,
                    background: 'rgba(0,0,0,.18)',
                    border: '1px solid rgba(255,255,255,.08)',
                    borderRadius: 10,
                    padding: '4px 10px 8px',
                  }}>
                    <AdvancedRow
                      label="Constellation Batch Size"
                      impact="medium"
                      help="控制星座圖的獨立樣本組數。"
                    >
                      <select
                        value={cfrAdvanced.constellationBatchSize}
                        onChange={e => updateCfrAdvanced('constellationBatchSize', Number(e.target.value))}
                        style={selectStyle}
                      >
                        <option value={1}>1</option>
                        <option value={10}>10</option>
                        <option value={50}>50</option>
                        <option value={100}>100</option>
                      </select>
                    </AdvancedRow>

                    <AdvancedRow
                      label="OFDM Subcarriers"
                      impact="high"
                      help="控制 CFR 頻域取樣點數。"
                    >
                      <select
                        value={cfrAdvanced.ofdmSubcarriers}
                        onChange={e => updateCfrAdvanced('ofdmSubcarriers', Number(e.target.value))}
                        style={selectStyle}
                      >
                        <option value={76}>76</option>
                        <option value={128}>128</option>
                        <option value={256}>256</option>
                        <option value={512}>512</option>
                      </select>
                    </AdvancedRow>

                    <AdvancedRow
                      label="Subcarrier Spacing"
                      impact="low"
                      help="控制相鄰子載波的頻率間隔。"
                    >
                      <NumberInput
                        value={cfrAdvanced.subcarrierSpacingHz / 1000}
                        step={15}
                        min={1}
                        max={240}
                        onChange={v => updateCfrAdvanced('subcarrierSpacingHz', clampNumber(v, 1, 240) * 1000)}
                      />
                    </AdvancedRow>

                    <AdvancedRow
                      label="Eb/N0"
                      impact="low"
                      help="控制訊號相對背景雜訊的品質。"
                    >
                      <NumberInput
                        value={cfrAdvanced.ebn0Db}
                        step={1}
                        min={0}
                        max={60}
                        onChange={v => updateCfrAdvanced('ebn0Db', clampNumber(v, 0, 60))}
                      />
                    </AdvancedRow>

                    <AdvancedRow
                      label="Ray Tracing Max Depth"
                      impact="high"
                      help="控制多路徑追蹤的最大互動深度。"
                    >
                      <select
                        value={cfrAdvanced.rayTracingMaxDepth}
                        onChange={e => updateCfrAdvanced('rayTracingMaxDepth', Number(e.target.value))}
                        style={selectStyle}
                      >
                        <option value={1}>1</option>
                        <option value={3}>3</option>
                        <option value={5}>5</option>
                        <option value={10}>10</option>
                      </select>
                    </AdvancedRow>
                  </div>
                )}
              </div>
            )}

            <button
              onClick={() => compute(tab)}
              disabled={cur.loading}
              style={{
                width:          '100%',
                padding:        '9px 0',
                background:     cur.loading
                  ? 'rgba(0,255,255,.08)'
                  : 'linear-gradient(135deg,rgba(0,255,255,.22),rgba(0,153,255,.25))',
                border:         '1px solid rgba(0,255,255,.35)',
                borderRadius:   10,
                color:          cur.loading ? 'rgba(0,255,255,.4)' : '#0ff',
                fontWeight:     700,
                fontSize:       13,
                cursor:         cur.loading ? 'not-allowed' : 'pointer',
                transition:     'all .2s',
                letterSpacing:  '.5px',
                marginBottom:   12,
              }}
            >
              {cur.loading ? '⏳ 計算中…' : '▶ 開始計算'}
            </button>

            {cur.error && (
              <div style={{
                background: 'rgba(255,50,80,.12)', border: '1px solid rgba(255,50,80,.3)',
                borderRadius: 8, padding: '8px 12px', color: '#ff6080', fontSize: 12, marginBottom: 10, wordBreak: 'break-all'
              }}>⚠ {cur.error}</div>
            )}

            {cur.imageUrl && tab === 'iss_unet' && cur.issUnetImages ? (
              <ISSUNetResultView
                images={cur.issUnetImages}
                cfarEnabled={issUnetParams.cfar_enabled}
                mode={issUnetParams.mode}
                metrics={cur.metrics}
                options={cur.options}
                activeView={issUnetActiveView}
                onViewChange={setIssUnetActiveView}
                onPreview={(url, title) => setPreview({ url, title })}
              />
            ) : cur.imageUrl ? (
              <div>
                <div style={{ borderRadius: 8, overflow: 'hidden', border: '1px solid rgba(0,255,255,.15)', boxShadow: '0 4px 20px rgba(0,0,0,.4)' }}>
                  <img
                    src={cur.imageUrl}
                    alt={tab}
                    style={{ width: '100%', display: 'block', cursor: 'zoom-in' }}
                    onClick={() => setPreview({
                      url: cur.imageUrl!,
                      title: tab === 'iss_unet' ? `ISS_UNET - ${ISS_UNET_MODE_LABELS[issUnetParams.mode]}` : tab.toUpperCase(),
                    })}
                    title="點擊查看完整圖片"
                  />
                </div>
              </div>
            ) : null}

            {!cur.loading && !cur.imageUrl && !cur.error && (
              <p style={{ textAlign: 'center', color: 'rgba(255,255,255,.25)', fontSize: 12, marginTop: 16 }}>
                按下「開始計算」以產生模擬圖
              </p>
            )}
          </div>
        </div>
      )}

      {preview && (
        <div className="sim-modal__overlay" onClick={() => setPreview(null)}>
          <div className="sim-modal__content" onClick={e => e.stopPropagation()}>
            <div className="sim-modal__header">
              <span className="sim-modal__title">{preview.title}</span>
              <button className="sim-modal__close" onClick={() => setPreview(null)}>×</button>
            </div>
            <div className="sim-modal__body">
              <img className="sim-modal__image" src={preview.url} alt={preview.title} />
            </div>
            <div className="sim-modal__footer">
              <a className="sim-modal__download" href={preview.url} download={`${preview.title.toLowerCase()}_map.png`}>
                下載圖片
              </a>
              <button className="sim-modal__btn-close" onClick={() => setPreview(null)}>
                關閉
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ISSUNetResultView({
  images,
  cfarEnabled,
  mode,
  metrics,
  options,
  activeView,
  onViewChange,
  onPreview,
}: {
  images: ISSUNetImages;
  cfarEnabled: boolean;
  mode: ISSUNetMode;
  metrics?: Record<string, unknown> | null;
  options?: Record<string, unknown> | null;
  activeView: ISSUNetViewKey;
  onViewChange: (v: ISSUNetViewKey) => void;
  onPreview: (url: string, title: string) => void;
}) {
  const cfarAvailable = cfarEnabled && images.cfar !== null;
  const url = images[activeView];

  // 如果 CFAR 沒開，但目前 activeView 是 cfar，自動切回 comparison
  useEffect(() => {
    if (activeView === 'cfar' && !cfarAvailable) {
      onViewChange('comparison');
    }
  }, [activeView, cfarAvailable, onViewChange]);

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 8 }}>
        <button
          onClick={() => onViewChange('comparison')}
          style={{
            padding: '6px 0',
            background: activeView === 'comparison' ? 'rgba(0,255,255,.18)' : 'rgba(0,0,0,.4)',
            border: activeView === 'comparison' ? '1px solid rgba(0,255,255,.6)' : '1px solid rgba(255,255,255,.1)',
            borderRadius: 6,
            color: activeView === 'comparison' ? '#0ff' : 'rgba(255,255,255,.6)',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'all .2s',
          }}
        >
          {ISS_UNET_VIEW_LABELS['comparison']}
        </button>
        <button
          onClick={() => { if (cfarAvailable) onViewChange('cfar') }}
          disabled={!cfarAvailable}
          style={{
            padding: '6px 0',
            background: activeView === 'cfar' ? 'rgba(0,255,255,.18)' : 'rgba(0,0,0,.4)',
            border: activeView === 'cfar' ? '1px solid rgba(0,255,255,.6)' : '1px solid rgba(255,255,255,.1)',
            borderRadius: 6,
            color: activeView === 'cfar' ? '#0ff' : (cfarAvailable ? 'rgba(255,255,255,.6)' : 'rgba(255,255,255,.2)'),
            fontSize: 12,
            fontWeight: 600,
            cursor: cfarAvailable ? 'pointer' : 'not-allowed',
            transition: 'all .2s',
          }}
          title={!cfarAvailable ? '請先啟用 CFAR' : ''}
        >
          {ISS_UNET_VIEW_LABELS['cfar']}{!cfarAvailable && ' (未啟用)'}
        </button>
      </div>

      <div style={{
        borderRadius: 6,
        overflow: 'hidden',
        border: '1px solid rgba(0,255,255,.12)',
        boxShadow: '0 2px 12px rgba(0,0,0,.35)',
        background: 'rgba(0,0,0,.3)',
        minHeight: 120,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 8,
      }}>
        {url ? (
          <img
            src={url}
            alt={ISS_UNET_VIEW_LABELS[activeView]}
            style={{ width: '100%', display: 'block', cursor: 'zoom-in' }}
            onClick={() => onPreview(url, `ISS_UNET - ${ISS_UNET_VIEW_LABELS[activeView]} (${ISS_UNET_MODE_LABELS[mode]})`)}
            title="點擊查看完整圖片"
          />
        ) : (
          <span style={{ color: 'rgba(255,255,255,.3)', fontSize: 11, padding: 16, textAlign: 'center' }}>
            {activeView === 'cfar' && !cfarAvailable ? 'CFAR 未啟用' : '無圖片'}
          </span>
        )}
      </div>

      {metrics && (
        <div style={{
          background: 'rgba(0,0,0,.22)',
          border: '1px solid rgba(255,255,255,.08)',
          borderRadius: 10,
          padding: '10px 12px',
          display: 'grid',
          gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
          gap: '6px 12px',
          color: 'rgba(255,255,255,.72)',
          fontSize: 12,
        }}>
          <div>Aligned Noise: {String(metrics.aligned_noise ?? '-')}</div>
          <div>Skipped Noise: {String(metrics.skipped_noise ?? '-')}</div>
          <div>Used Samples: {String(metrics.used_samples ?? '-')}</div>
          <div>Sparse Samples: {String(metrics.sparse_samples ?? '-')}</div>
          <div>Route Points: {String(metrics.route_points ?? '-')}</div>
          <div>Mask: {options?.apply_building_mask === false ? 'Off' : 'On'}</div>
        </div>
      )}
    </div>
  );
}

function ParamGrid({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'minmax(80px, auto) 1fr',
      gap: '8px 12px', alignItems: 'center', background: 'rgba(0,0,0,.2)', padding: 12, borderRadius: 12
    }}>
      {children}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return <div style={{ color: 'rgba(255,255,255,.6)', fontSize: 12 }}>{children}</div>;
}

function Hint({ children }: { children: React.ReactNode }) {
  return <div style={{ color: 'rgba(255,255,255,.36)', fontSize: 11, lineHeight: 1.35 }}>{children}</div>;
}

function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))`,
      gap: 3,
      background: 'rgba(0,0,0,.28)',
      border: '1px solid rgba(255,255,255,.1)',
      borderRadius: 8,
      padding: 3,
    }}>
      {options.map(option => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            style={{
              minHeight: 25,
              padding: '4px 6px',
              border: active ? '1px solid rgba(0,255,255,.45)' : '1px solid transparent',
              borderRadius: 6,
              background: active ? 'rgba(0,255,255,.18)' : 'transparent',
              color: active ? '#0ff' : 'rgba(255,255,255,.56)',
              fontSize: 11,
              fontWeight: active ? 700 : 500,
              cursor: 'pointer',
              whiteSpace: 'normal',
              lineHeight: 1.15,
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function FileInput({
  file,
  accept,
  onChange,
}: {
  file: File | null;
  accept: string;
  onChange: (file: File | null) => void;
}) {
  return (
    <label style={{
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      minHeight: 30,
      background: 'rgba(0,0,0,.3)',
      border: '1px solid rgba(255,255,255,.1)',
      color: file ? 'rgba(255,255,255,.82)' : 'rgba(255,255,255,.42)',
      padding: '4px 8px',
      borderRadius: 6,
      fontSize: 12,
      cursor: 'pointer',
      overflow: 'hidden',
    }}>
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {file ? file.name : 'Use sample'}
      </span>
      {file && (
        <button
          type="button"
          onClick={event => {
            event.preventDefault();
            onChange(null);
          }}
          style={{
            border: 'none',
            background: 'transparent',
            color: 'rgba(255,255,255,.45)',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          x
        </button>
      )}
      <input
        type="file"
        accept={accept}
        onChange={event => onChange(event.currentTarget.files?.[0] ?? null)}
        style={{ display: 'none' }}
      />
    </label>
  );
}

function ImpactBadge({ impact }: { impact: ComputeImpact }) {
  const meta = {
    low: {
      label: '低',
      color: '#43d17a',
      background: 'rgba(67,209,122,.14)',
      border: 'rgba(67,209,122,.35)',
    },
    medium: {
      label: '中',
      color: '#ffd166',
      background: 'rgba(255,209,102,.14)',
      border: 'rgba(255,209,102,.35)',
    },
    high: {
      label: '高',
      color: '#ff5c7a',
      background: 'rgba(255,92,122,.14)',
      border: 'rgba(255,92,122,.35)',
    },
  }[impact];

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      minWidth: 28,
      padding: '2px 6px',
      borderRadius: 6,
      border: `1px solid ${meta.border}`,
      background: meta.background,
      color: meta.color,
      fontSize: 11,
      fontWeight: 700,
    }}>
      {meta.label}
    </span>
  );
}

function AdvancedRow({
  label,
  impact,
  help,
  children,
}: {
  label: string;
  impact: ComputeImpact;
  help: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'minmax(150px, 1fr) minmax(120px, 150px) auto',
      gap: '6px 8px',
      alignItems: 'center',
      padding: '8px 0',
      borderTop: '1px solid rgba(255,255,255,.07)',
    }}>
      <div style={{ color: 'rgba(255,255,255,.72)', fontSize: 12, fontWeight: 600 }}>
        {label}
      </div>
      <div>{children}</div>
      <ImpactBadge impact={impact} />
      <div style={{
        gridColumn: '1 / -1',
        color: 'rgba(255,255,255,.38)',
        fontSize: 11,
        lineHeight: 1.35,
      }}>
        {help}
      </div>
    </div>
  );
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function NumberInput({
  value,
  step,
  min,
  max,
  disabled = false,
  onChange,
}: {
  value: number,
  step: number,
  min: number,
  max: number,
  disabled?: boolean,
  onChange: (v: number) => void,
}) {
  return (
    <input type="number" step={step} min={min} max={max} value={value} disabled={disabled}
      onChange={e => onChange(Number(e.target.value))}
      style={{
        background: 'rgba(0,0,0,.3)', border: '1px solid rgba(255,255,255,.1)',
        color: disabled ? 'rgba(255,255,255,.32)' : '#fff',
        padding: '4px 8px',
        borderRadius: 6,
        fontSize: 12,
        width: '100%',
        cursor: disabled ? 'not-allowed' : 'text',
      }}
    />
  );
}

function ToggleSwitch({
  checked,
  disabled = false,
  onChange,
}: {
  checked: boolean,
  disabled?: boolean,
  onChange: (v: boolean) => void,
}) {
  return (
    <button
      type="button"
      onClick={() => {
        if (!disabled) {
          onChange(!checked);
        }
      }}
      aria-pressed={checked}
      disabled={disabled}
      style={{
        width: 40,
        height: 20,
        border: checked && !disabled ? '1px solid rgba(0,255,255,.55)' : '1px solid rgba(255,255,255,.16)',
        borderRadius: 12,
        background: disabled
          ? 'rgba(255,255,255,.08)'
          : (checked ? 'rgba(0, 255, 0, 0.22)' : 'rgba(255, 0, 0, 0.25)'),
        padding: 2,
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: checked ? 'flex-end' : 'flex-start',
        transition: 'all .15s',
        opacity: disabled ? 0.55 : 1,
      }}
      title={disabled ? 'Noise with GPS only' : (checked ? 'On' : 'Off')}
    >
      <span
        style={{
          width: 15,
          height: 15,
          borderRadius: 12,
          background: checked && !disabled ? '#0ff' : 'rgba(255,255,255,.45)',
          boxShadow: checked && !disabled ? '0 0 10px rgba(0,255,255,.45)' : 'none',
          display: 'block',
        }}
      />
    </button>
  );
}

const selectStyle = {
  background: 'rgba(0,0,0,.3)', border: '1px solid rgba(255,255,255,.1)', color: '#fff',
  padding: '4px 8px', borderRadius: 6, fontSize: 12, width: '100%', cursor: 'pointer'
};
