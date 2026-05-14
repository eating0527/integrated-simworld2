import { SCENES, type SceneId } from '@/config/scenes.config';
import { type GeneratedSceneOption } from '@/hooks/useGeneratedScene';
import { useEffect, useRef, useState } from 'react';

export type SelectedScene =
  | { source: 'preset'; id: SceneId }
  | { source: 'generated'; taskId: string };

interface SceneSwitcherProps {
  selectedScene: SelectedScene;
  generatedScenes: GeneratedSceneOption[];
  generatedStatus?: 'idle' | 'loading' | 'polling' | 'error';
  onSelectPreset: (id: SceneId) => void;
  onSelectGenerated: (taskId: string) => void;
}

const buttonBaseStyle = {
  padding: '6px 18px',
  borderRadius: '8px',
  border: 'none',
  fontSize: '13px',
  letterSpacing: '0.04em',
  transition: 'all 0.2s',
} as const;

function subtitleStyle(maxWidth = '120px') {
  return {
    display: 'block',
    fontSize: '10px',
    fontWeight: 400,
    opacity: 0.75,
    marginTop: '1px',
    maxWidth,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  } as const;
}

const generatedDisplayStyle = {
  position: 'relative',
  zIndex: 1,
  width: '100%',
  display: 'grid',
  gridTemplateColumns: '1fr auto',
  columnGap: '8px',
  alignItems: 'center',
  pointerEvents: 'none',
} as const;

const generatedTextStackStyle = {
  minWidth: 0,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  lineHeight: 1.1,
} as const;

const generatedMenuStyle = {
  position: 'absolute',
  top: 'calc(100% + 8px)',
  left: 0,
  right: 0,
  padding: '6px',
  borderRadius: '10px',
  border: '1px solid rgba(148,163,184,0.22)',
  background: 'rgba(13,17,23,0.96)',
  backdropFilter: 'blur(14px)',
  WebkitBackdropFilter: 'blur(14px)',
  boxShadow: '0 16px 40px rgba(0,0,0,0.45), 0 0 0 1px rgba(15,23,42,0.8)',
  maxHeight: '260px',
  overflowY: 'auto',
  zIndex: 1001,
} as const;

const generatedOptionBaseStyle = {
  width: '100%',
  border: 'none',
  borderRadius: '7px',
  padding: '7px 9px',
  background: 'transparent',
  color: 'rgba(226,232,240,0.88)',
  fontSize: '12px',
  lineHeight: 1.25,
  textAlign: 'left',
  whiteSpace: 'nowrap',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  cursor: 'pointer',
  transition: 'background 0.15s, color 0.15s',
} as const;

export function SceneSwitcher({
  selectedScene,
  generatedScenes,
  generatedStatus = 'idle',
  onSelectPreset,
  onSelectGenerated,
}: SceneSwitcherProps) {
  const [generatedHovered, setGeneratedHovered] = useState(false);
  const [generatedFocused, setGeneratedFocused] = useState(false);
  const [generatedOpen, setGeneratedOpen] = useState(false);
  const [hoveredGeneratedTaskId, setHoveredGeneratedTaskId] = useState<string | null>(null);
  const generatedContainerRef = useRef<HTMLDivElement | null>(null);
  const selectedGeneratedScene = selectedScene.source === 'generated'
    ? generatedScenes.find(scene => scene.taskId === selectedScene.taskId)
    : null;
  const generatedActive = selectedScene.source === 'generated';
  const hasGeneratedScenes = generatedScenes.length > 0;
  const generatedLabel = selectedGeneratedScene?.label
    ?? (generatedStatus === 'polling' ? 'Generating...' : 'Select scene');
  const generatedInteractive = hasGeneratedScenes;
  const generatedMuted = !generatedInteractive && generatedStatus !== 'polling';

  useEffect(() => {
    if (!generatedOpen) return;

    function handlePointerDown(event: PointerEvent) {
      if (!generatedContainerRef.current?.contains(event.target as Node)) {
        setGeneratedOpen(false);
        setGeneratedFocused(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setGeneratedOpen(false);
        setGeneratedFocused(false);
      }
    }

    window.addEventListener('pointerdown', handlePointerDown);
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('pointerdown', handlePointerDown);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [generatedOpen]);

  useEffect(() => {
    if (!hasGeneratedScenes) {
      setGeneratedOpen(false);
    }
  }, [hasGeneratedScenes]);

  return (
    <div style={{
      position: 'fixed',
      top: '16px',
      left: '50%',
      transform: 'translateX(-50%)',
      display: 'flex',
      gap: '8px',
      zIndex: 1000,
      background: 'rgba(10, 15, 30, 0.75)',
      backdropFilter: 'blur(12px)',
      WebkitBackdropFilter: 'blur(12px)',
      border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: '12px',
      padding: '6px',
      boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
    }}>
      {SCENES.map(scene => {
        const active = selectedScene.source === 'preset' && selectedScene.id === scene.id;
        return (
          <button
            key={scene.id}
            onClick={() => onSelectPreset(scene.id)}
            title={scene.label}
            style={{
              ...buttonBaseStyle,
              cursor: 'pointer',
              fontWeight: active ? 700 : 400,
              background: active
                ? 'linear-gradient(135deg, rgba(99,179,237,0.9), rgba(129,140,248,0.9))'
                : 'transparent',
              color: active ? '#fff' : 'rgba(255,255,255,0.6)',
              boxShadow: active ? '0 2px 12px rgba(99,179,237,0.35)' : 'none',
            }}
          >
            {scene.labelEn}
            <span style={subtitleStyle()}>
              {scene.label}
            </span>
          </button>
        );
      })}

      <div
        ref={generatedContainerRef}
        title={hasGeneratedScenes ? generatedLabel : 'No generated scenes available'}
        onMouseEnter={() => setGeneratedHovered(true)}
        onMouseLeave={() => setGeneratedHovered(false)}
        style={{
          ...buttonBaseStyle,
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minWidth: '150px',
          maxWidth: '190px',
          overflow: 'visible',
          fontWeight: generatedActive ? 700 : 400,
          background: generatedActive
            ? 'linear-gradient(135deg, rgba(16,185,129,0.9), rgba(59,130,246,0.9))'
            : generatedHovered && generatedInteractive
              ? 'rgba(16,185,129,0.12)'
              : 'transparent',
          color: !generatedMuted
            ? (generatedActive ? '#fff' : 'rgba(255,255,255,0.7)')
            : 'rgba(255,255,255,0.35)',
          boxShadow: generatedActive
            ? '0 2px 12px rgba(16,185,129,0.35)'
            : generatedFocused || generatedOpen
              ? '0 0 0 1px rgba(45,212,191,0.45), 0 2px 12px rgba(16,185,129,0.2)'
              : 'none',
          outline: generatedFocused || generatedOpen ? '1px solid rgba(45,212,191,0.55)' : '1px solid transparent',
          cursor: generatedInteractive ? 'pointer' : 'not-allowed',
        }}
      >
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={generatedOpen}
          disabled={!hasGeneratedScenes}
          onClick={() => {
            if (!hasGeneratedScenes) return;
            setGeneratedOpen(open => !open);
            setGeneratedFocused(true);
          }}
          onFocus={() => setGeneratedFocused(true)}
          onBlur={(event) => {
            if (!generatedContainerRef.current?.contains(event.relatedTarget as Node | null)) {
              setGeneratedFocused(false);
            }
          }}
          onKeyDown={(event) => {
            if ((event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') && hasGeneratedScenes) {
              event.preventDefault();
              setGeneratedOpen(true);
            }
          }}
          style={{
            position: 'absolute',
            inset: 0,
            border: 'none',
            padding: 0,
            background: 'transparent',
            color: 'inherit',
            cursor: hasGeneratedScenes ? 'pointer' : 'not-allowed',
          }}
        />
        <span style={generatedDisplayStyle}>
          <span style={generatedTextStackStyle}>
            <span>Generated</span>
            <span style={subtitleStyle('128px')}>
              {generatedLabel}
            </span>
          </span>
          <span
            aria-hidden="true"
            style={{
              color: generatedActive ? '#d1fae5' : 'rgba(45,212,191,0.75)',
              width: 0,
              height: 0,
              borderLeft: '4px solid transparent',
              borderRight: '4px solid transparent',
              borderTop: '5px solid currentColor',
              transform: generatedOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s, color 0.2s',
            }}
          />
        </span>
        {generatedOpen && (
          <div className="gen-menu" role="listbox" aria-label="Generated scenes" style={generatedMenuStyle}>
            {generatedScenes.map(scene => {
              const selected = selectedGeneratedScene?.taskId === scene.taskId;
              const hovered = hoveredGeneratedTaskId === scene.taskId;

              return (
                <button
                  key={scene.taskId}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  title={scene.label}
                  onMouseEnter={() => setHoveredGeneratedTaskId(scene.taskId)}
                  onMouseLeave={() => setHoveredGeneratedTaskId(null)}
                  onClick={() => {
                    onSelectGenerated(scene.taskId);
                    setGeneratedOpen(false);
                    setGeneratedFocused(false);
                  }}
                  style={{
                    ...generatedOptionBaseStyle,
                    fontWeight: selected ? 700 : 500,
                    background: selected
                      ? 'linear-gradient(135deg, rgba(16,185,129,0.95), rgba(37,99,235,0.95))'
                      : hovered
                        ? 'rgba(45,212,191,0.12)'
                        : 'transparent',
                    color: selected ? '#fff' : 'rgba(226,232,240,0.88)',
                    boxShadow: selected ? '0 6px 18px rgba(16,185,129,0.24)' : 'none',
                  }}
                >
                  {scene.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
