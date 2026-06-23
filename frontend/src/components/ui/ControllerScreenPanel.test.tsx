import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { ControllerScreenPanel } from './ControllerScreenPanel';

describe('ControllerScreenPanel', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows the AP3 panel title once', () => {
    render(<ControllerScreenPanel />);

    expect(screen.getAllByText('無人機畫面')).toHaveLength(1);
  });
});
