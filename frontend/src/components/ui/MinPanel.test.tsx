import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MinPanel } from './MinPanel';

describe('MinPanel', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('collapses to the panel title and restores the content', async () => {
    const user = userEvent.setup();

    render(
      <MinPanel title="USRP 設定">
        <button>Start sampling</button>
      </MinPanel>,
    );

    expect(screen.getByRole('button', { name: 'Start sampling' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /minimize usrp 設定/i }));

    expect(screen.queryByRole('button', { name: 'Start sampling' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /restore usrp 設定/i })).toHaveTextContent('USRP 設定');

    await user.click(screen.getByRole('button', { name: /restore usrp 設定/i }));

    expect(screen.getByRole('button', { name: 'Start sampling' })).toBeInTheDocument();
  });

  it('moves only while the title is held and dragged', () => {
    const { container } = render(
      <MinPanel title="無人機控制" draggable style={{ position: 'fixed', left: 10, top: 20 }}>
        <button>Move</button>
      </MinPanel>,
    );
    const panel = container.firstElementChild as HTMLElement;
    const title = screen.getByRole('button', { name: /minimize 無人機控制/i });

    fireEvent.pointerDown(title, { clientX: 20, clientY: 30 });
    fireEvent.pointerMove(window, { clientX: 70, clientY: 90 });
    fireEvent.pointerUp(window);

    expect(panel.style.left).toBe('60px');
    expect(panel.style.top).toBe('80px');
  });

  it('does not move after a released click', () => {
    const { container } = render(
      <MinPanel title="無人機控制" draggable style={{ position: 'fixed', left: 10, top: 20 }}>
        <button>Move</button>
      </MinPanel>,
    );
    const panel = container.firstElementChild as HTMLElement;
    const title = screen.getByRole('button', { name: /minimize 無人機控制/i });

    fireEvent.pointerDown(title, { clientX: 20, clientY: 30 });
    fireEvent.pointerUp(window);
    fireEvent.pointerMove(window, { clientX: 70, clientY: 90 });

    expect(panel.style.left).toBe('10px');
    expect(panel.style.top).toBe('20px');
  });

  it('anchors minimized size to the current upper-left corner', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MinPanel title="Panel" style={{ position: 'fixed', right: 14, bottom: 60, width: 440 }}>
        <button>Inside</button>
      </MinPanel>,
    );
    const panel = container.firstElementChild as HTMLElement;
    panel.getBoundingClientRect = () => ({
      left: 120,
      top: 80,
      right: 560,
      bottom: 300,
      width: 440,
      height: 220,
      x: 120,
      y: 80,
      toJSON: () => ({}),
    } as DOMRect);

    await user.click(screen.getByRole('button', { name: /minimize panel/i }));

    expect(panel.style.left).toBe('120px');
    expect(panel.style.top).toBe('80px');
    expect(panel.style.right).toBe('auto');
    expect(panel.style.bottom).toBe('auto');
    expect(panel.style.width).toBe('max-content');
    expect(panel.style.height).toBe('max-content');
  });
});
