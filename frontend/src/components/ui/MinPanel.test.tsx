import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { MinPanel } from './MinPanel';

describe('MinPanel', () => {
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

  it('reports whether the panel is expanded', async () => {
    const user = userEvent.setup();

    render(
      <MinPanel title="Panel">
        <button>Inside</button>
      </MinPanel>,
    );

    const title = screen.getByRole('button', { name: /minimize panel/i });
    expect(title).toHaveAttribute('aria-expanded', 'true');

    await user.click(title);

    expect(screen.getByRole('button', { name: /restore panel/i })).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps collapsed content mounted but removes it from the accessibility tree', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MinPanel title="Panel">
        <button>Inside</button>
      </MinPanel>,
    );

    await user.click(screen.getByRole('button', { name: /minimize panel/i }));

    expect(screen.getByText('Inside').closest('button')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Inside' })).not.toBeInTheDocument();
    expect(container.querySelector('.min-panel__body')).toHaveAttribute('inert');
  });

  it('starts secondary panels collapsed without unmounting their content', () => {
    const { container } = render(
      <MinPanel title="Secondary" defaultMinimized>
        <button>Secondary action</button>
      </MinPanel>,
    );

    expect(screen.getByRole('button', { name: /restore secondary/i })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Secondary action').closest('button')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Secondary action' })).not.toBeInTheDocument();
    expect(container.querySelector('.min-panel__body')).toHaveAttribute('inert');
  });

  it('supports controlled minimized state and change notifications', async () => {
    const user = userEvent.setup();
    const onMinimizedChange = vi.fn();

    function ControlledPanel() {
      const [minimized, setMinimized] = useState(true);
      return (
        <MinPanel
          title="Panel"
          minimized={minimized}
          onMinimizedChange={value => {
            onMinimizedChange(value);
            setMinimized(value);
          }}
        >
          <button>Details</button>
        </MinPanel>
      );
    }

    const { container } = render(<ControlledPanel />);

    expect(screen.getByRole('button', { name: /restore panel/i })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('Details').closest('button')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Details' })).not.toBeInTheDocument();
    expect(container.querySelector('.min-panel__body')).toHaveAttribute('inert');

    await user.click(screen.getByRole('button', { name: /restore panel/i }));

    expect(onMinimizedChange).toHaveBeenCalledWith(false);
    expect(screen.getByRole('button', { name: /minimize panel/i })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('button', { name: 'Details' })).toBeVisible();
    expect(container.querySelector('.min-panel__body')).not.toHaveAttribute('inert');
  });
});
