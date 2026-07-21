/**
 * PhotoViewer — 照片歷史面板（電腦端，Glassmorphism）
 */
import { useEffect, useRef, useState } from 'react';

interface Photo {
  url: string;
  timestamp: string;
  filename: string;
  latitude?: number | null;
  longitude?: number | null;
  altitude?: number | null;
  deviceId?: string | null;
}

interface Props {
  photos: Photo[];
  onDelete?: (filename: string) => void;
}

const API = import.meta.env.VITE_API_URL || '';

function parseTimestamp(ts: string): Date {
  const m = ts.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/);
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6]));
  return new Date(ts);
}

export function PhotoViewer({ photos, onDelete }: Props) {
  const [selected, setSelected] = useState<Photo | null>(null);
  const [collapsed, setCollapsed] = useState(true);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const lastTrigger = useRef<HTMLElement | null>(null);
  const closeButton = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!selected) {
      lastTrigger.current?.focus();
      return;
    }
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelected(null);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [selected]);

  if (photos.length === 0) return null;

  const full = (url: string) => /^https?:\/\//i.test(url) ? url : `${API}${url}`;
  const closeDialog = () => setSelected(null);

  const handleDelete = async (photo: Photo, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`刪除照片 ${photo.filename}？`)) return;
    try {
      const response = await fetch(`${API}/api/delete-photo/${encodeURIComponent(photo.filename)}`, { method: 'DELETE' });
      const payload = await response.json();
      if (!response.ok || payload.success !== true) throw new Error('delete failed');
      if (selected?.filename === photo.filename) setSelected(null);
      onDelete?.(photo.filename);
    } catch { alert('刪除失敗'); }
  };

  return (
    <>
      <div className="photo-viewer panel-ui" style={{
        background: 'rgba(8,12,28,0.75)', backdropFilter: 'blur(18px)', WebkitBackdropFilter: 'blur(18px)',
        border: '1px solid rgba(120,180,255,0.14)', borderRadius: 'var(--panel-radius)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06)',
        maxHeight: collapsed ? 52 : '62vh', overflow: 'hidden', display: 'flex', flexDirection: 'column',
        transition: 'max-height 0.35s cubic-bezier(0.4,0,0.2,1)', animation: 'slide-in-right 0.3s ease',
      }}>
        <button className="photo-viewer__header" aria-expanded={!collapsed} aria-controls="photo-viewer-history" onClick={() => setCollapsed(c => !c)}>
          <span style={{ fontSize: 14 }}>🖼️</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13, flex: 1 }}>照片</span>
          <span style={{ background: 'rgba(0,212,255,0.15)', color: 'var(--accent-cyan)', fontSize: 11, fontWeight: 700, padding: '1px 7px', borderRadius: 10 }}>{photos.length}</span>
          <span style={{ color: 'var(--text-dim)', fontSize: 11, marginLeft: 2 }}>{collapsed ? '▲' : '▼'}</span>
        </button>
        {!collapsed && <div id="photo-viewer-history" style={{ overflowY: 'auto', flex: 1, padding: '8px 8px 10px' }}>
          {photos.map((p, i) => <div key={p.filename} className="photo-viewer__card-wrap" onMouseEnter={() => setHoveredIdx(i)} onMouseLeave={() => setHoveredIdx(null)}>
            <button className="photo-viewer__card" aria-label={`開啟照片 ${p.filename}`} onClick={(e) => { lastTrigger.current = e.currentTarget; setSelected(p); }} style={{
              position: 'relative', marginBottom: 8, cursor: 'pointer', borderRadius: 10, overflow: 'hidden', width: '100%', padding: 0,
              border: `1.5px solid ${selected?.filename === p.filename ? 'rgba(0,212,255,0.6)' : hoveredIdx === i ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.06)'}`,
              boxShadow: selected?.filename === p.filename ? '0 0 12px rgba(0,212,255,0.3)' : 'none', transition: 'border 0.2s, box-shadow 0.2s, transform 0.15s', transform: hoveredIdx === i ? 'scale(1.02)' : 'scale(1)',
            }}>
              <img src={full(p.url)} alt={p.filename} style={{ width: '100%', display: 'block', aspectRatio: '4/3', objectFit: 'cover' }} />
              <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, background: 'linear-gradient(transparent, rgba(0,0,0,0.82))', padding: '16px 7px 6px', textAlign: 'left' }}>
                <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.85)', fontWeight: 600, lineHeight: 1.4 }}>{parseTimestamp(p.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</div>
                <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.5)', lineHeight: 1.3 }}>{parseTimestamp(p.timestamp).toLocaleDateString([], { month: '2-digit', day: '2-digit', year: 'numeric' })}</div>
              </div>
            </button>
            <button className="photo-viewer__delete" aria-label={`刪除照片 ${p.filename}`} onClick={(e) => handleDelete(p, e)}>×</button>
          </div>)}
        </div>}
      </div>
      {selected && <div className="photo-viewer__dialog" role="dialog" aria-modal="true" aria-labelledby="photo-viewer-dialog-title" onClick={(e) => { if (e.target === e.currentTarget) closeDialog(); }}>
        <button ref={closeButton} className="photo-viewer__close" aria-label="關閉照片" onClick={closeDialog}>×</button>
        <div style={{ background: 'rgba(8,12,28,0.8)', border: '1px solid rgba(120,180,255,0.2)', borderRadius: 20, padding: 10, boxShadow: '0 0 60px rgba(0,212,255,0.15), 0 20px 60px rgba(0,0,0,0.7)' }}>
          <img src={full(selected.url)} alt={selected.filename} style={{ maxWidth: '85vw', maxHeight: '72vh', borderRadius: 12, display: 'block' }} />
        </div>
        <div style={{ textAlign: 'center' }}><div id="photo-viewer-dialog-title" style={{ color: '#e8eaf6', fontSize: 13, marginBottom: 4 }}>{selected.filename}</div><div style={{ color: '#e8eaf6', fontSize: 13 }}>{parseTimestamp(selected.timestamp).toLocaleString()}</div>
          {selected.latitude != null && <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontFamily: 'monospace' }}>{selected.latitude.toFixed(6)}, {selected.longitude?.toFixed(6)}{selected.altitude != null && <span> ↕ {selected.altitude.toFixed(1)} m</span>}</div>}
        </div>
      </div>}
    </>
  );
}
