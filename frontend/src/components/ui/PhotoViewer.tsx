/**
 * PhotoViewer — 照片歷史面板（電腦端，Glassmorphism）
 */
import { useState } from 'react';

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
  apiBase?: string;
  onDelete?: (filename: string) => void;
}

const API = import.meta.env.VITE_API_URL ?? 'https://backend.simworld.website';

/** 解析後端 "20260307_163115" 格式，回傳 Date（若已是 ISO 格式也相容） */
function parseTimestamp(ts: string): Date {
  // 格式：YYYYMMDD_HHMMSS
  const m = ts.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/);
  if (m) {
    return new Date(
      Number(m[1]), Number(m[2]) - 1, Number(m[3]),
      Number(m[4]), Number(m[5]), Number(m[6])
    );
  }
  // fallback：ISO / 其他格式
  return new Date(ts);
}

export function PhotoViewer({ photos, onDelete }: Props) {
  const [selected, setSelected] = useState<Photo | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  if (photos.length === 0) return null;

  const full = (url: string) => url.startsWith('http') ? url : `${API}${url}`;

  const handleDelete = async (photo: Photo, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`刪除照片 ${photo.filename}？`)) return;
    try {
      await fetch(`${API}/api/delete-photo/${photo.filename}`, { method: 'DELETE' });
      onDelete?.(photo.filename);
    } catch { alert('刪除失敗'); }
  };

  return (
    <>
      {/* ── 照片歷史面板 ── */}
      <div style={{
        position: 'fixed', bottom: 70, right: 14, zIndex: 900,
        background: 'rgba(8,12,28,0.75)',
        backdropFilter: 'blur(18px)',
        WebkitBackdropFilter: 'blur(18px)',
        border: '1px solid rgba(120,180,255,0.14)',
        borderRadius: 'var(--panel-radius)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.06)',
        width: 154,
        maxHeight: collapsed ? 52 : '62vh',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        transition: 'max-height 0.35s cubic-bezier(0.4,0,0.2,1)',
        animation: 'slide-in-right 0.3s ease',
      }}>
        {/* 標題列 */}
        <div
          onClick={() => setCollapsed(c => !c)}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '13px 14px',
            cursor: 'pointer',
            userSelect: 'none',
            borderBottom: collapsed ? 'none' : '1px solid rgba(120,180,255,0.08)',
          }}
        >
          <span style={{ fontSize: 14 }}>🖼️</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: 13, flex: 1 }}>照片</span>
          <span style={{
            background: 'rgba(0,212,255,0.15)',
            color: 'var(--accent-cyan)',
            fontSize: 11, fontWeight: 700,
            padding: '1px 7px', borderRadius: 10,
          }}>{photos.length}</span>
          <span style={{ color: 'var(--text-dim)', fontSize: 11, marginLeft: 2 }}>
            {collapsed ? '▲' : '▼'}
          </span>
        </div>

        {/* 照片歷史 */}
        {!collapsed && (
          <div style={{ overflowY: 'auto', flex: 1, padding: '8px 8px 10px' }}>
            {photos.map((p, i) => (
              <div
                key={i}
                onClick={() => setSelected(p)}
                onMouseEnter={() => setHoveredIdx(i)}
                onMouseLeave={() => setHoveredIdx(null)}
                style={{
                  position: 'relative',
                  marginBottom: 8,
                  cursor: 'pointer',
                  borderRadius: 10,
                  overflow: 'hidden',
                  border: `1.5px solid ${
                    selected?.filename === p.filename
                      ? 'rgba(0,212,255,0.6)'
                      : hoveredIdx === i
                        ? 'rgba(255,255,255,0.18)'
                        : 'rgba(255,255,255,0.06)'
                  }`,
                  boxShadow: selected?.filename === p.filename
                    ? '0 0 12px rgba(0,212,255,0.3)' : 'none',
                  transition: 'border 0.2s, box-shadow 0.2s, transform 0.15s',
                  transform: hoveredIdx === i ? 'scale(1.02)' : 'scale(1)',
                }}>
                <img
                  src={full(p.url)}
                  alt={p.filename}
                  style={{ width: '100%', display: 'block', aspectRatio: '4/3', objectFit: 'cover' }}
                />
                {/* 日期+時間標籤 */}
                <div style={{
                  position: 'absolute', bottom: 0, left: 0, right: 0,
                  background: 'linear-gradient(transparent, rgba(0,0,0,0.82))',
                  padding: '16px 7px 6px',
                }}>
                  <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.85)', fontWeight: 600, lineHeight: 1.4 }}>
                    {parseTimestamp(p.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </div>
                  <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.5)', lineHeight: 1.3 }}>
                    {parseTimestamp(p.timestamp).toLocaleDateString([], { month: '2-digit', day: '2-digit', year: 'numeric' })}
                  </div>
                </div>
                {/* 刪除按鈕 */}
                <button
                  onClick={(e) => handleDelete(p, e)}
                  style={{
                    position: 'absolute', top: 5, right: 5,
                    width: 20, height: 20,
                    background: 'rgba(0,0,0,0.6)',
                    backdropFilter: 'blur(4px)',
                    color: 'rgba(255,255,255,0.7)',
                    border: '1px solid rgba(255,255,255,0.15)',
                    borderRadius: '50%',
                    fontSize: 10, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    opacity: hoveredIdx === i ? 1 : 0,
                    transition: 'opacity 0.2s',
                  }}
                >×</button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── 全螢幕登的 Lightbox ── */}
      {selected && (
        <div
          onClick={() => setSelected(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 2000,
            background: 'rgba(4,6,16,0.92)',
            backdropFilter: 'blur(12px)',
            WebkitBackdropFilter: 'blur(12px)',
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 16,
            animation: 'fade-in 0.2s ease',
          }}
        >
          {/* 圖片容器 */}
          <div style={{
            background: 'rgba(8,12,28,0.8)',
            border: '1px solid rgba(120,180,255,0.2)',
            borderRadius: 20,
            padding: 10,
            boxShadow: '0 0 60px rgba(0,212,255,0.15), 0 20px 60px rgba(0,0,0,0.7)',
          }}>
            <img
              src={full(selected.url)}
              alt={selected.filename}
              style={{ maxWidth: '85vw', maxHeight: '72vh', borderRadius: 12, display: 'block' }}
            />
          </div>
          {/* 元資料 */}
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: '#e8eaf6', fontSize: 13, marginBottom: 4 }}>
              {parseTimestamp(selected.timestamp).toLocaleString()}
            </div>
            {selected.latitude != null && (
              <div style={{ color: 'var(--text-secondary)', fontSize: 12, fontFamily: 'monospace' }}>
                {selected.latitude.toFixed(6)}, {selected.longitude?.toFixed(6)}
                {selected.altitude != null && <span>  ↕ {selected.altitude.toFixed(1)} m</span>}
              </div>
            )}
          </div>
          <div style={{
            color: 'var(--text-dim)', fontSize: 12,
            border: '1px solid rgba(120,180,255,0.1)',
            padding: '4px 16px', borderRadius: 20,
          }}>點擊任意處關閉</div>
        </div>
      )}
    </>
  );
}
