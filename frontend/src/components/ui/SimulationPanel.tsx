import { useState, useCallback } from 'react';
import { useDeviceStore } from '../../store/useDeviceStore';
import { useEffect } from 'react';

const API = import.meta.env.VITE_API_URL || '';

type TabKey = 'sinr' | 'cfr' | 'doppler' | 'channel' | 'iss' | 'tss' | 'cfar';
type CFRModulation = 'qpsk' | '16qam';
type ComputeImpact = 'low' | 'medium' | 'high';

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

interface SimStatus {
  loading: boolean;
  imageUrl: string | null;
  error: string | null;
}

const EMPTY: SimStatus = { loading: false, imageUrl: null, error: null };
const GENERATED_SCENE_TABS: TabKey[] = ['cfr', 'iss', 'tss', 'cfar'];
const DEFAULT_CFR_ADVANCED: CFRAdvancedParams = {
  constellationBatchSize: 1,
  ofdmSubcarriers: 76,
  subcarrierSpacingHz: 30000,
  ebn0Db: 20,
  rayTracingMaxDepth: 10,
};

function buildSinrUrl(params: SINRParams): string {
  const q = new URLSearchParams({
    sinr_vmin: String(params.sinr_vmin),
    sinr_vmax: String(params.sinr_vmax),
    cell_size:  String(params.cell_size),
    samples_per_tx: String(params.samples_per_tx),
  });
  return `${API}/api/sionna/sinr-map?${q.toString()}`;
}

interface SimulationPanelProps {
  sceneId?: string | null;
  generatedScene?: boolean;
}

export function SimulationPanel({ sceneId = 'NTPU', generatedScene = false }: SimulationPanelProps) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<TabKey>('sinr');
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(null);
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
  });

  const [sinrParams, setSinrParams] = useState<SINRParams>({
    sinr_vmin: -20,
    sinr_vmax: 40,
    cell_size: 3.0,
    samples_per_tx: 100000000,
  });

  const devices = useDeviceStore(state => state.devices);

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

    if (generatedScene && !GENERATED_SCENE_TABS.includes(key)) {
      setStatus(prev => ({
        ...prev,
        [key]: {
          loading: false,
          imageUrl: null,
          error: 'Generated scene currently supports CFR/ISS/TSS/CFAR maps only.',
        },
      }));
      return;
    }

    setStatus(prev => ({ ...prev, [key]: { loading: true, imageUrl: null, error: null } }));

    try {
      let res;
      if (key === 'cfr') {
        const requestSceneId = sceneId ?? 'NTPU';
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
            devices: devices.map(d => ({
              name: d.name,
              role: d.role,
              x: d.x,
              y: d.y,
              z: d.z,
              power_dbm: d.powerDbm ?? null,
            })),
          }),
        });
      } else if (['iss', 'tss', 'cfar'].includes(key)) {
        const requestSceneId = sceneId ?? 'NTPU';
        res = await fetch(`${API}/api/simulate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            scene: requestSceneId,
            map_type: key,
            cell_size: sinrParams.cell_size,
            samples_per_tx: sinrParams.samples_per_tx,
            overlay_scene: overlayScene,
            devices: devices.map(d => ({
              name: d.name,
              role: d.role,
              x: d.x,
              y: d.y,
              z: d.z,
              power_dbm: d.powerDbm ?? null,
            })),
          }),
        });
      } else {
        const urlMap: Record<string, string> = {
          sinr:    buildSinrUrl(sinrParams),
          doppler: `${API}/api/sionna/doppler`,
          channel: `${API}/api/sionna/channel-response`,
        };
        res = await fetch(urlMap[key]);
      }

      if (!res.ok) {
        const json = await res.json().catch(() => ({ error: 'HTTP Error' }));
        throw new Error(json.detail || json.error || 'HTTP Error');
      }
      
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      setStatus(prev => ({ ...prev, [key]: { loading: false, imageUrl: url, error: null } }));
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatus(prev => ({ ...prev, [key]: { loading: false, imageUrl: null, error: msg } }));
    }
  }, [sinrParams, sceneId, devices, overlayScene, generatedScene, cfrModulation, cfrAdvanced]);

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
                  {tab !== 'sinr' && (
                    <>
                      <Label>場景輪廓</Label>
                      <ToggleSwitch checked={overlayScene} onChange={setOverlayScene} />
                    </>
                  )}
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

            {cur.imageUrl && (
              <div style={{ borderRadius: 8, overflow: 'hidden', border: '1px solid rgba(0,255,255,.15)', boxShadow: '0 4px 20px rgba(0,0,0,.4)' }}>
                <img
                  src={cur.imageUrl}
                  alt={tab}
                  style={{ width: '100%', display: 'block', cursor: 'zoom-in' }}
                  onClick={() => setPreview({ url: cur.imageUrl!, title: tab.toUpperCase() })}
                  title="點擊查看完整圖片"
                />
              </div>
            )}

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

function NumberInput({ value, step, min, max, onChange }: { value: number, step: number, min: number, max: number, onChange: (v: number) => void }) {
  return (
    <input type="number" step={step} min={min} max={max} value={value}
      onChange={e => onChange(Number(e.target.value))}
      style={{
        background: 'rgba(0,0,0,.3)', border: '1px solid rgba(255,255,255,.1)',
        color: '#fff', padding: '4px 8px', borderRadius: 6, fontSize: 12, width: '100%'
      }}
    />
  );
}

function ToggleSwitch({ checked, onChange }: { checked: boolean, onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
      style={{
        width: 40,
        height: 20,
        border: checked ? '1px solid rgba(0,255,255,.55)' : '1px solid rgba(255,255,255,.16)',
        borderRadius: 12,
        background: checked ? 'rgba(0, 255, 0, 0.22)' : 'rgba(255, 0, 0, 0.25)',
        padding: 2,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: checked ? 'flex-end' : 'flex-start',
        transition: 'all .15s',
      }}
      title={checked ? 'On' : 'Off'}
    >
      <span
        style={{
          width: 15,
          height: 15,
          borderRadius: 12,
          background: checked ? '#0ff' : 'rgba(255,255,255,.45)',
          boxShadow: checked ? '0 0 10px rgba(0,255,255,.45)' : 'none',
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
