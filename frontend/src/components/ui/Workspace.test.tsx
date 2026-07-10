import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Workspace } from './Workspace';

function renderWorkspace() {
  render(
    <Workspace
      top={<div>場景列</div>}
      left={<div>左側內容</div>}
      right={<div>右側內容</div>}
    >
      <div>3D 場景</div>
    </Workspace>,
  );
}

describe('Workspace', () => {
  it('toggles desktop rails independently', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    expect(screen.getByText('場景列')).toBeInTheDocument();
    expect(screen.getByText('3D 場景')).toBeInTheDocument();

    const left = screen.getByRole('button', { name: '切換左側工作區' });
    const right = screen.getByRole('button', { name: '切換右側工作區' });
    expect(left).toHaveAttribute('aria-expanded', 'true');
    expect(right).toHaveAttribute('aria-expanded', 'true');

    await user.click(left);

    expect(left).toHaveAttribute('aria-expanded', 'false');
    expect(right).toHaveAttribute('aria-expanded', 'true');
  });

  it('switches mobile rails mutually exclusively and closes with Escape', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const left = screen.getByRole('button', { name: '開啟左側工作區' });
    const right = screen.getByRole('button', { name: '開啟右側工作區' });
    expect(left).toHaveAttribute('aria-expanded', 'false');
    expect(right).toHaveAttribute('aria-expanded', 'false');

    await user.click(left);
    expect(left).toHaveAttribute('aria-expanded', 'true');
    expect(right).toHaveAttribute('aria-expanded', 'false');

    await user.click(right);
    expect(left).toHaveAttribute('aria-expanded', 'false');
    expect(right).toHaveAttribute('aria-expanded', 'true');

    await user.keyboard('{Escape}');
    expect(right).toHaveAttribute('aria-expanded', 'false');
  });
});
