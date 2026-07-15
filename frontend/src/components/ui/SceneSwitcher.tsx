import { DEFAULT_SCENE_ID, SCENES, type SceneId } from '@/config/scenes.config';
import {
  getBuildLabel,
  isSceneBuilding,
  type GeneratedSceneOption,
  type SceneMutationResult,
} from '@/hooks/useGeneratedScene';
import { useEffect, useRef, useState, type FormEvent } from 'react';

export type SelectedScene =
  | { source: 'preset'; id: SceneId }
  | { source: 'generated'; taskId: string };

interface SceneSwitcherProps {
  selectedScene: SelectedScene;
  generatedScenes: GeneratedSceneOption[];
  generatedStatus?: 'idle' | 'loading' | 'polling' | 'error';
  onSelectPreset: (id: SceneId) => void;
  onSelectGenerated: (taskId: string) => void;
  onRenameGenerated: (taskId: string, displayName: string, token: string) => Promise<SceneMutationResult>;
  onDeleteGenerated: (taskId: string, token: string) => Promise<SceneMutationResult>;
}

type SceneDialog = { type: 'edit' | 'delete'; scene: GeneratedSceneOption };

export function SceneSwitcher({
  selectedScene,
  generatedScenes,
  generatedStatus = 'idle',
  onSelectPreset,
  onSelectGenerated,
  onRenameGenerated,
  onDeleteGenerated,
}: SceneSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState<SceneDialog | null>(null);
  const [token, setToken] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const containerRef = useRef<HTMLElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const actionRef = useRef<HTMLButtonElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);
  const dialogRef = useRef<HTMLFormElement | null>(null);
  const isBuilding = generatedScenes.some(isSceneBuilding);
  useEffect(() => {
    if (!open) return;

    const closeOnPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !dialog) setOpen(false);
    };

    window.addEventListener('pointerdown', closeOnPointerDown);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('pointerdown', closeOnPointerDown);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [dialog, open]);

  useEffect(() => {
    if (!dialog) return;
    firstFieldRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !saving) {
        setDialog(null);
        requestAnimationFrame(() => {
          if (actionRef.current?.isConnected) actionRef.current.focus();
          else toggleRef.current?.focus();
        });
      }
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [dialog, saving]);

  const openDialog = (type: SceneDialog['type'], scene: GeneratedSceneOption, button: HTMLButtonElement) => {
    actionRef.current = button;
    setDialog({ type, scene });
    setName(scene.label);
    setError('');
  };

  const closeDialog = () => {
    if (saving) return;
    setDialog(null);
    requestAnimationFrame(() => {
      if (actionRef.current?.isConnected) actionRef.current.focus();
      else toggleRef.current?.focus();
    });
  };

  const submitDialog = async (event: FormEvent) => {
    event.preventDefault();
    if (!dialog || !token.trim()) {
      setError('請輸入管理權杖');
      return;
    }
    const nextName = name.trim();
    if (dialog.type === 'edit' && (!nextName || nextName.length > 80)) {
      setError('場景名稱需為 1–80 個字元');
      return;
    }

    setSaving(true);
    setError('');
    const result = dialog.type === 'edit'
      ? await onRenameGenerated(dialog.scene.taskId, nextName, token)
      : await onDeleteGenerated(dialog.scene.taskId, token);
    setSaving(false);
    if (!result.ok) {
      if (result.status === 403) setToken('');
      setError(result.error ?? '操作失敗');
      return;
    }
    if (dialog.type === 'delete'
      && selectedScene.source === 'generated'
      && selectedScene.taskId === dialog.scene.taskId) {
      onSelectPreset(DEFAULT_SCENE_ID);
    }
    setOpen(false);
    closeDialog();
  };

  return (
    <nav ref={containerRef} className="scene-switcher" aria-label="場景選擇">
      <button
        ref={toggleRef}
        type="button"
        className="scene-switcher__toggle"
        aria-label="SCENE"
        aria-expanded={open}
        aria-controls="scene-options"
        onClick={() => setOpen(value => !value)}
      >
        <span>SCENE</span>
        <span className="scene-switcher__chevron" aria-hidden="true">⌄</span>
      </button>

      {open && (
        <div id="scene-options" className="scene-switcher__menu" role="group" aria-label="Scene options">
          {SCENES.map(scene => {
            const selected = selectedScene.source === 'preset' && selectedScene.id === scene.id;
            return (
              <button
                key={scene.id}
                type="button"
                className={`scene-switcher__option${selected ? ' is-selected' : ''}`}
                aria-current={selected ? 'true' : undefined}
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
            const statusLabel = getBuildLabel(scene);
            const canEdit = scene.status === 'completed' && scene.ready;
            const canDelete = canEdit || scene.status === 'failed';
            return (
              <div className="scene-switcher__row" key={scene.taskId}>
                <button
                  type="button"
                  className={`scene-switcher__option${selected ? ' is-selected' : ''}`}
                  aria-current={selected ? 'true' : undefined}
                  disabled={Boolean(statusLabel)}
                  onClick={() => {
                    onSelectGenerated(scene.taskId);
                    setOpen(false);
                  }}
                >
                  {scene.label}
                  {statusLabel && <span className="scene-switcher__subtitle">{statusLabel}</span>}
                </button>
                {canEdit && (
                  <button
                    type="button"
                    className="scene-switcher__action"
                    aria-label={`編輯 ${scene.label}`}
                    onClick={event => openDialog('edit', scene, event.currentTarget)}
                  >
                    編輯
                  </button>
                )}
                {canDelete && (
                  <button
                    type="button"
                    className="scene-switcher__action is-danger"
                    aria-label={`刪除 ${scene.label}`}
                    onClick={event => openDialog('delete', scene, event.currentTarget)}
                  >
                    刪除
                  </button>
                )}
              </div>
            );
          })}
          {isBuilding ? (
            <button type="button" className="scene-switcher__option scene-switcher__create" disabled>
              <span aria-hidden="true">+</span> 建立新場景
            </button>
          ) : (
            <a className="scene-switcher__option scene-switcher__create" href="/my_map.html">
              <span aria-hidden="true">+</span> 建立新場景
            </a>
          )}
          {generatedStatus === 'loading' && (
            <span className="scene-switcher__empty">Loading scenes...</span>
          )}
        </div>
      )}
      {dialog && (
        <div className="sim-modal__overlay scene-dialog" role="presentation">
          <form
            ref={dialogRef}
            className="sim-modal__content scene-dialog__content"
            role="dialog"
            aria-modal="true"
            aria-labelledby="scene-dialog-title"
            onSubmit={submitDialog}
            onBlurCapture={event => {
              if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
              const fields = event.currentTarget.querySelectorAll<HTMLElement>(
                'button:not(:disabled), input:not(:disabled)',
              );
              if (event.target === fields[0]) fields[fields.length - 1]?.focus();
              else firstFieldRef.current?.focus();
            }}
          >
            <div className="sim-modal__header">
              <h2 className="sim-modal__title" id="scene-dialog-title">
                {dialog.type === 'edit' ? '確認編輯場景名稱' : '確認刪除場景'}
              </h2>
              <button
                type="button"
                className="sim-modal__close"
                aria-label="關閉"
                disabled={saving}
                onClick={closeDialog}
              >×</button>
            </div>
            <div className="sim-modal__body scene-dialog__body">
              {dialog.type === 'edit' ? (
                <label>
                  顯示名稱
                  <input
                    ref={firstFieldRef}
                    value={name}
                    maxLength={80}
                    onChange={event => setName(event.target.value)}
                  />
                </label>
              ) : (
                <p>將永久刪除「{dialog.scene.label}」的場景資料；已生成圖片會保留。</p>
              )}
              <label>
                管理權杖
                <input
                  ref={dialog.type === 'delete' ? firstFieldRef : undefined}
                  type="password"
                  value={token}
                  autoComplete="off"
                  onChange={event => setToken(event.target.value)}
                />
              </label>
              {error && <p className="scene-dialog__error" role="alert">{error}</p>}
            </div>
            <div className="sim-modal__footer">
              <button type="button" className="sim-modal__btn-close" disabled={saving} onClick={closeDialog}>取消</button>
              <button type="submit" className="scene-dialog__confirm" disabled={saving}>
                {saving ? '處理中…' : '確認'}
              </button>
            </div>
          </form>
        </div>
      )}
    </nav>
  );
}
