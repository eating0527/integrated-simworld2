import { SCENES, type SceneId } from '@/config/scenes.config';
import { type GeneratedSceneOption } from '@/hooks/useGeneratedScene';

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

export function SceneSwitcher({
  selectedScene,
  generatedScenes,
  generatedStatus = 'idle',
  onSelectPreset,
  onSelectGenerated,
}: SceneSwitcherProps) {
  const selectedGeneratedScene = selectedScene.source === 'generated'
    ? generatedScenes.find(scene => scene.taskId === selectedScene.taskId)
    : null;
  const generatedActive = selectedScene.source === 'generated';
  const hasGeneratedScenes = generatedScenes.length > 0;
  const generatedLabel = selectedGeneratedScene?.label
    ?? (generatedStatus === 'polling' ? 'Generating...' : 'Select scene');

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

      <label
        title={hasGeneratedScenes ? generatedLabel : 'No generated scenes available'}
        style={{
          ...buttonBaseStyle,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minWidth: '150px',
          fontWeight: generatedActive ? 700 : 400,
          background: generatedActive
            ? 'linear-gradient(135deg, rgba(16,185,129,0.9), rgba(59,130,246,0.9))'
            : 'transparent',
          color: hasGeneratedScenes || generatedStatus === 'polling'
            ? (generatedActive ? '#fff' : 'rgba(255,255,255,0.7)')
            : 'rgba(255,255,255,0.35)',
          boxShadow: generatedActive ? '0 2px 12px rgba(16,185,129,0.35)' : 'none',
        }}
      >
        Generated
        <select
          value={selectedGeneratedScene?.taskId ?? ''}
          disabled={!hasGeneratedScenes}
          onChange={(event) => {
            if (event.target.value) {
              onSelectGenerated(event.target.value);
            }
          }}
          style={{
            width: '130px',
            marginTop: '2px',
            border: 'none',
            outline: 'none',
            cursor: hasGeneratedScenes ? 'pointer' : 'not-allowed',
            background: 'transparent',
            color: 'inherit',
            fontSize: '10px',
            textAlign: 'center',
            opacity: 0.8,
          }}
        >
          <option value="" style={{ color: '#111' }}>
            {generatedLabel}
          </option>
          {generatedScenes.map(scene => (
            <option key={scene.taskId} value={scene.taskId} style={{ color: '#111' }}>
              {scene.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
