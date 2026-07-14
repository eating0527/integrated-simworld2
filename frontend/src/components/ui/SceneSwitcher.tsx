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
  onBackToMap: () => void;
}

export function SceneSwitcher({
  selectedScene,
  generatedScenes,
  generatedStatus = 'idle',
  onSelectPreset,
  onSelectGenerated,
  onBackToMap,
}: SceneSwitcherProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!open) return;

    const closeOnPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };

    window.addEventListener('pointerdown', closeOnPointerDown);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('pointerdown', closeOnPointerDown);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  return (
    <nav ref={containerRef} className="scene-switcher" aria-label="Scene switcher">
      <button
        type="button"
        className="scene-switcher__toggle"
        aria-label="SCENE"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(value => !value)}
      >
        <span>SCENE</span>
        <span className="scene-switcher__chevron" aria-hidden="true">⌄</span>
      </button>

      {open && (
        <div className="scene-switcher__menu" role="listbox" aria-label="Scene options">
          {SCENES.map(scene => {
            const selected = selectedScene.source === 'preset' && selectedScene.id === scene.id;
            return (
              <button
                key={scene.id}
                type="button"
                className={`scene-switcher__option${selected ? ' is-selected' : ''}`}
                aria-selected={selected}
                onClick={() => {
                  onSelectPreset(scene.id);
                  setOpen(false);
                }}
              >
                {scene.labelEn}
              </button>
            );
          })}
          {generatedScenes.map(scene => {
            const selected = selectedScene.source === 'generated' && selectedScene.taskId === scene.taskId;
            return (
              <button
                key={scene.taskId}
                type="button"
                className={`scene-switcher__option${selected ? ' is-selected' : ''}`}
                aria-selected={selected}
                onClick={() => {
                  onSelectGenerated(scene.taskId);
                  setOpen(false);
                }}
              >
                {scene.label}
              </button>
            );
          })}
          {generatedStatus === 'loading' && (
            <span className="scene-switcher__empty">Loading scenes...</span>
          )}
          <button
            type="button"
            className="scene-switcher__option"
            onClick={() => {
              setOpen(false);
              onBackToMap();
            }}
          >
            Return to map
          </button>
        </div>
      )}
    </nav>
  );
}
