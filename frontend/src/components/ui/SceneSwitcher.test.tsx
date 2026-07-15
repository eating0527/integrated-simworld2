import { render, screen } from '@testing-library/react';
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

function renderSceneSwitcher(generatedScenes = [generatedScene]) {
  const onSelectPreset = vi.fn();
  const onSelectGenerated = vi.fn();

  render(
    <SceneSwitcher
      selectedScene={{ source: 'preset', id: 'ntpu' }}
      generatedScenes={generatedScenes}
      onSelectPreset={onSelectPreset}
      onSelectGenerated={onSelectGenerated}
    />,
  );

  return { onSelectPreset, onSelectGenerated };
}

describe('SceneSwitcher', () => {
  it('opens a vertical scene menu and selects preset and generated scenes', async () => {
    const user = userEvent.setup();
    const { onSelectPreset, onSelectGenerated } = renderSceneSwitcher();

    expect(screen.getByRole('navigation', { name: '場景選擇' })).toHaveClass('scene-switcher');

    await user.click(screen.getByRole('button', { name: 'SCENE' }));
    expect(screen.getByRole('listbox', { name: 'Scene options' })).toBeInTheDocument();
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
    expect(screen.getByRole('listbox', { name: 'Scene options' })).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('listbox', { name: 'Scene options' })).not.toBeInTheDocument();
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
});
