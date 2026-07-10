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

export function SceneSwitcher({
  selectedScene,
  generatedScenes,
  generatedStatus = 'idle',
  onSelectPreset,
  onSelectGenerated,
}: SceneSwitcherProps) {
  const [generatedOpen, setGeneratedOpen] = useState(false);
  const generatedContainerRef = useRef<HTMLDivElement | null>(null);
  const selectedGeneratedScene = selectedScene.source === 'generated'
    ? generatedScenes.find(scene => scene.taskId === selectedScene.taskId)
    : null;
  const generatedActive = selectedScene.source === 'generated';
  const hasGeneratedScenes = generatedScenes.length > 0;
  const generatedLabel = selectedGeneratedScene?.label
    ?? (generatedStatus === 'polling' ? 'Generating...' : 'Select scene');
  const generatedMuted = !hasGeneratedScenes && generatedStatus !== 'polling';

  useEffect(() => {
    if (!generatedOpen) return;

    function handlePointerDown(event: PointerEvent) {
      if (!generatedContainerRef.current?.contains(event.target as Node)) {
        setGeneratedOpen(false);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setGeneratedOpen(false);
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
    <nav className="scene-switcher" aria-label="場景選擇">
      <span className="scene-switcher__eyebrow">SCENE</span>
      <div className="scene-switcher__presets">
        {SCENES.map(scene => {
          const active = selectedScene.source === 'preset' && selectedScene.id === scene.id;

          return (
            <button
              key={scene.id}
              type="button"
              className={`scene-switcher__button${active ? ' is-active' : ''}`}
              aria-pressed={active}
              onClick={() => onSelectPreset(scene.id)}
              title={scene.label}
            >
              {scene.labelEn}
              <span className="scene-switcher__subtitle">{scene.label}</span>
            </button>
          );
        })}
      </div>

      <div
        ref={generatedContainerRef}
        className={`scene-switcher__generated${generatedActive ? ' is-active' : ''}${generatedOpen ? ' is-open' : ''}${generatedMuted ? ' is-muted' : ''}`}
      >
        <button
          type="button"
          className="scene-switcher__generated-button"
          title={hasGeneratedScenes ? generatedLabel : 'No generated scenes available'}
          aria-haspopup="listbox"
          aria-expanded={generatedOpen}
          disabled={!hasGeneratedScenes}
          onClick={() => {
            if (!hasGeneratedScenes) return;
            setGeneratedOpen(open => !open);
          }}
          onKeyDown={(event) => {
            if ((event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') && hasGeneratedScenes) {
              event.preventDefault();
              setGeneratedOpen(true);
            }
          }}
        >
          <span>
            Generated
            <span className="scene-switcher__subtitle">{generatedLabel}</span>
          </span>
          <span className="scene-switcher__chevron" aria-hidden="true" />
        </button>
        {generatedOpen && (
          <div className="scene-switcher__menu gen-menu" role="listbox" aria-label="Generated scenes">
            {generatedScenes.map(scene => {
              const selected = selectedGeneratedScene?.taskId === scene.taskId;

              return (
                <button
                  key={scene.taskId}
                  type="button"
                  className={`scene-switcher__option${selected ? ' is-selected' : ''}`}
                  role="option"
                  aria-selected={selected}
                  title={scene.label}
                  onClick={() => {
                    onSelectGenerated(scene.taskId);
                    setGeneratedOpen(false);
                  }}
                >
                  {scene.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </nav>
  );
}
