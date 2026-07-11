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
};

function renderSceneSwitcher() {
  const onSelectPreset = vi.fn();
  const onSelectGenerated = vi.fn();

  render(
    <SceneSwitcher
      selectedScene={{ source: 'preset', id: 'ntpu' }}
      generatedScenes={[generatedScene]}
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
});
