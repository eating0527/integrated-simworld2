import { describe, expect, it } from 'vitest';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Workspace } from './Workspace';

function renderWorkspace() {
  return render(
    <Workspace
      top={<div>場景列</div>}
      left={<><button type="button">左側第一項</button><button type="button">左側最後項</button></>}
      right={<><button type="button">右側第一項</button><button type="button">右側最後項</button></>}
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
    expect(screen.getByRole('complementary', { name: '左側工作區' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: '右側工作區' })).toBeInTheDocument();

    const statusHeader = screen.getByRole('banner');
    const left = screen.getByRole('button', { name: '切換左側工作區' });
    const right = screen.getByRole('button', { name: '切換右側工作區' });
    expect(within(statusHeader).getByRole('button', { name: '切換左側工作區' })).toBe(left);
    expect(within(statusHeader).getByRole('button', { name: '切換右側工作區' })).toBe(right);
    expect(left).toHaveAttribute('aria-expanded', 'true');
    expect(right).toHaveAttribute('aria-expanded', 'true');

    await user.click(left);

    expect(left).toHaveAttribute('aria-expanded', 'false');
    expect(right).toHaveAttribute('aria-expanded', 'true');
  });

  it('uses rail IDs scoped to each Workspace instance', () => {
    const { container } = render(
      <>
        <Workspace left={<div>第一個左側</div>} right={<div>第一個右側</div>}>
          <div>第一個場景</div>
        </Workspace>
        <Workspace left={<div>第二個左側</div>} right={<div>第二個右側</div>}>
          <div>第二個場景</div>
        </Workspace>
      </>,
    );

    const workspaces = Array.from(container.querySelectorAll<HTMLElement>('.workspace'));
    const rails = Array.from(container.querySelectorAll<HTMLElement>('aside.workspace__rail'));
    expect(rails).toHaveLength(4);
    expect(new Set(rails.map(rail => rail.id)).size).toBe(4);

    for (const workspace of workspaces) {
      const instanceRails = Array.from(workspace.querySelectorAll<HTMLElement>('aside.workspace__rail'));
      const leftRail = instanceRails.find(rail => rail.classList.contains('workspace__rail--left'));
      const rightRail = instanceRails.find(rail => rail.classList.contains('workspace__rail--right'));

      expect(instanceRails).toHaveLength(2);
      expect(leftRail).toBeDefined();
      expect(rightRail).toBeDefined();
      expect(within(workspace).getByRole('button', { name: '切換左側工作區' })).toHaveAttribute(
        'aria-controls',
        leftRail!.id,
      );
      expect(within(workspace).getByRole('button', { name: '開啟左側工作區' })).toHaveAttribute(
        'aria-controls',
        leftRail!.id,
      );
      expect(within(workspace).getByRole('button', { name: '切換右側工作區' })).toHaveAttribute(
        'aria-controls',
        rightRail!.id,
      );
      expect(within(workspace).getByRole('button', { name: '開啟右側工作區' })).toHaveAttribute(
        'aria-controls',
        rightRail!.id,
      );
    }
  });

  it('switches mobile rails mutually exclusively and uses the current action label to close', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const left = screen.getByRole('button', { name: '開啟左側工作區' });
    const right = screen.getByRole('button', { name: '開啟右側工作區' });
    expect(left).toHaveAttribute('aria-expanded', 'false');
    expect(right).toHaveAttribute('aria-expanded', 'false');

    await user.click(left);
    expect(screen.getByRole('button', { name: '關閉左側工作區' })).toHaveAttribute('aria-expanded', 'true');
    expect(right).toHaveAttribute('aria-expanded', 'false');

    await user.click(right);
    expect(screen.getByRole('button', { name: '開啟左側工作區' })).toHaveAttribute('aria-expanded', 'false');
    const closeRight = screen.getByRole('button', { name: '關閉右側工作區' });
    expect(closeRight).toHaveAttribute('aria-expanded', 'true');

    await user.click(closeRight);
    expect(screen.getByRole('button', { name: '開啟右側工作區' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps the mobile drawer open for a prevented Escape and otherwise closes it', async () => {
    const user = userEvent.setup();
    const preventEscape = (event: KeyboardEvent) => event.preventDefault();
    window.addEventListener('keydown', preventEscape);

    try {
      renderWorkspace();
      await user.click(screen.getByRole('button', { name: '開啟左側工作區' }));

      act(() => {
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }));
      });
      expect(screen.getByRole('button', { name: '關閉左側工作區' })).toHaveAttribute('aria-expanded', 'true');

      window.removeEventListener('keydown', preventEscape);
      await user.keyboard('{Escape}');
      expect(screen.getByRole('button', { name: '開啟左側工作區' })).toHaveAttribute('aria-expanded', 'false');
    } finally {
      window.removeEventListener('keydown', preventEscape);
    }
  });

  it('opens the mobile rail as a focus-trapped dialog and restores focus on Escape', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const trigger = screen.getByRole('button', { name: '開啟左側工作區' });
    await user.click(trigger);

    const dialog = screen.getByRole('dialog', { name: '左側工作區' });
    const first = within(dialog).getByRole('button', { name: '左側第一項' });
    const last = within(dialog).getByRole('button', { name: '左側最後項' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(first).toHaveFocus();

    last.focus();
    await user.tab();
    expect(first).toHaveFocus();

    await user.tab({ shift: true });
    expect(last).toHaveFocus();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: '左側工作區' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '開啟左側工作區' })).toHaveFocus();
  });

  it('restores focus after closing a mobile drawer from its backdrop', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const trigger = screen.getByRole('button', { name: '開啟右側工作區' });
    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: '關閉側欄' }));

    expect(trigger).toHaveFocus();
  });

  it('closes the mobile drawer from its backdrop', async () => {
    const user = userEvent.setup();
    renderWorkspace();

    const right = screen.getByRole('button', { name: '開啟右側工作區' });
    await user.click(right);
    expect(right).toHaveAttribute('aria-expanded', 'true');

    await user.click(screen.getByRole('button', { name: '關閉側欄' }));
    expect(right).toHaveAttribute('aria-expanded', 'false');
  });
});
