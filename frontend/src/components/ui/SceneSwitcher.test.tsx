import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { type GeneratedSceneOption } from '@/hooks/useGeneratedScene';
import { SceneSwitcher } from './SceneSwitcher';

const generatedScene: GeneratedSceneOption = {
  taskId: 'task-1',
  sceneKey: 'custom',
  label: '自訂場景',
  modelPath: '/scene.glb',
  createdAt: '2026-07-10',
  status: 'completed',
  ready: true,
};

function renderSceneSwitcher(
  generatedScenes = [generatedScene],
  selectedScene = { source: 'preset', id: 'ntpu' } as const,
) {
  const onSelectPreset = vi.fn();
  const onSelectGenerated = vi.fn();
  const onRenameGenerated = vi.fn().mockResolvedValue({ ok: true, status: 200 });
  const onDeleteGenerated = vi.fn().mockResolvedValue({ ok: true, status: 200 });

  render(
    <SceneSwitcher
      selectedScene={selectedScene}
      generatedScenes={generatedScenes}
      onSelectPreset={onSelectPreset}
      onSelectGenerated={onSelectGenerated}
      onRenameGenerated={onRenameGenerated}
      onDeleteGenerated={onDeleteGenerated}
    />,
  );

  return { onSelectPreset, onSelectGenerated, onRenameGenerated, onDeleteGenerated };
}

describe('SceneSwitcher', () => {
  it('opens a vertical scene menu and selects preset and generated scenes', async () => {
    const user = userEvent.setup();
    const { onSelectPreset, onSelectGenerated } = renderSceneSwitcher();

    expect(screen.getByRole('navigation', { name: '場景選擇' })).toHaveClass('scene-switcher');

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    expect(screen.getByRole('group', { name: 'Scene options' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'SCENE' })).toHaveAttribute('aria-controls', 'scene-options');
    expect(screen.getByRole('button', { name: 'NTPU' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'NYCU' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '自訂場景' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '建立新場景' })).toHaveClass('scene-switcher__create');
    expect(screen.getByRole('link', { name: '建立新場景' })).toHaveAttribute('href', '/my_map.html');

    await user.click(screen.getByRole('button', { name: 'NYCU' }));
    expect(onSelectPreset).toHaveBeenCalledWith('nycu');

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    await user.click(screen.getByRole('button', { name: '自訂場景' }));
    expect(onSelectGenerated).toHaveBeenCalledWith('task-1');
  });

  it('closes the scene menu with Escape', async () => {
    const user = userEvent.setup();
    renderSceneSwitcher();

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    expect(screen.getByRole('group', { name: 'Scene options' })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('group', { name: 'Scene options' })).not.toBeInTheDocument();
  });

  it('disables scene creation and unfinished scenes while showing build status', async () => {
    const user = userEvent.setup();
    const pendingScene = {
      ...generatedScene,
      taskId: 'task-pending',
      label: '正在建立的場景',
      status: 'running',
      stage: 'running_blender_generation',
      ready: false,
    } as GeneratedSceneOption;
    renderSceneSwitcher([pendingScene]);

    await user.click(screen.getByRole('button', { name: 'SCENE' }));

    const scene = screen.getByRole('button', { name: /正在建立的場景/ });
    expect(scene).toBeDisabled();
    expect(scene).toHaveTextContent('正在建立 3D 場景');
    expect(screen.getByRole('button', { name: '建立新場景' })).toBeDisabled();
  });

  it('shows management actions only for completed and failed scenes', async () => {
    const user = userEvent.setup();
    const failedScene = {
      ...generatedScene,
      taskId: 'task-failed',
      label: '失敗場景',
      status: 'failed',
      ready: false,
    } as GeneratedSceneOption;
    renderSceneSwitcher([generatedScene, failedScene]);

    await user.click(screen.getByRole('button', { name: 'SCENE' }));

    expect(screen.getByRole('button', { name: '編輯 自訂場景' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刪除 自訂場景' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '編輯 失敗場景' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刪除 失敗場景' })).toBeInTheDocument();
  });

  it('confirms a persistent display-name edit with an in-memory admin token', async () => {
    const user = userEvent.setup();
    const { onRenameGenerated } = renderSceneSwitcher();

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    await user.click(screen.getByRole('button', { name: '編輯 自訂場景' }));

    expect(screen.getByRole('dialog', { name: '確認編輯場景名稱' })).toBeInTheDocument();
    await user.clear(screen.getByRole('textbox', { name: '顯示名稱' }));
    await user.type(screen.getByRole('textbox', { name: '顯示名稱' }), '新顯示名稱');
    await user.type(screen.getByLabelText('管理權杖'), 'secret');
    await user.click(screen.getByRole('button', { name: '確認' }));

    expect(onRenameGenerated).toHaveBeenCalledWith('task-1', '新顯示名稱', 'secret');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps delete confirmation open and clears an invalid token after 403', async () => {
    const user = userEvent.setup();
    const { onDeleteGenerated } = renderSceneSwitcher();
    onDeleteGenerated.mockResolvedValue({ ok: false, status: 403, error: '刪除場景失敗 (403)' });

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    await user.click(screen.getByRole('button', { name: '刪除 自訂場景' }));
    const token = screen.getByLabelText('管理權杖');
    await user.type(token, 'wrong');
    await user.click(screen.getByRole('button', { name: '確認' }));

    expect(onDeleteGenerated).toHaveBeenCalledWith('task-1', 'wrong');
    expect(screen.getByRole('alert')).toHaveTextContent('刪除場景失敗 (403)');
    expect(token).toHaveValue('');
  });

  it('closes a confirmation dialog with Escape', async () => {
    const user = userEvent.setup();
    renderSceneSwitcher();

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    await user.click(screen.getByRole('button', { name: '刪除 自訂場景' }));
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '刪除 自訂場景' })).toHaveFocus());
  });

  it('keeps focus inside the confirmation dialog', async () => {
    const user = userEvent.setup();
    renderSceneSwitcher();

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    await user.click(screen.getByRole('button', { name: '刪除 自訂場景' }));
    const confirm = screen.getByRole('button', { name: '確認' });
    confirm.focus();
    await user.tab();

    expect(screen.getByLabelText('管理權杖')).toHaveFocus();
  });

  it('cannot close the confirmation while a mutation is running', async () => {
    const user = userEvent.setup();
    let finish!: (value: { ok: boolean; status: number }) => void;
    const { onDeleteGenerated } = renderSceneSwitcher();
    onDeleteGenerated.mockReturnValue(new Promise(resolve => { finish = resolve; }));

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    await user.click(screen.getByRole('button', { name: '刪除 自訂場景' }));
    await user.type(screen.getByLabelText('管理權杖'), 'secret');
    await user.click(screen.getByRole('button', { name: '確認' }));

    expect(screen.getByRole('button', { name: '關閉' })).toBeDisabled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    finish({ ok: true, status: 200 });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('returns to NTPU after deleting the active generated scene', async () => {
    const user = userEvent.setup();
    const { onSelectPreset } = renderSceneSwitcher(
      [generatedScene],
      { source: 'generated', taskId: 'task-1' },
    );

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    await user.click(screen.getByRole('button', { name: '刪除 自訂場景' }));
    await user.type(screen.getByLabelText('管理權杖'), 'secret');
    await user.click(screen.getByRole('button', { name: '確認' }));

    await waitFor(() => expect(onSelectPreset).toHaveBeenCalledWith('ntpu'));
  });
});
