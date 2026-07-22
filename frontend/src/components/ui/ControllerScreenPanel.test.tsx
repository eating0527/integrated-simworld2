import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { ControllerScreenPanel } from './ControllerScreenPanel';

describe('ControllerScreenPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows the AP3 panel title once and keeps the monitor closed by default', () => {
    render(<ControllerScreenPanel />);

    expect(screen.getAllByText('無人機畫面')).toHaveLength(1);
    expect(screen.getByRole('button', { name: /restore/i })).toHaveAttribute('aria-expanded', 'false');
  });
});
