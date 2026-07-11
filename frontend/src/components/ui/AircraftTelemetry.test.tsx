import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { AircraftTelemetry } from './AircraftTelemetry';

describe('AircraftTelemetry', () => {
  afterEach(() => {
    cleanup();
  });

  it('shows the panel title once', () => {
    render(<AircraftTelemetry device={null} isTracked={false} />);

    expect(screen.getAllByText('無人機遙測')).toHaveLength(1);
  });
});
