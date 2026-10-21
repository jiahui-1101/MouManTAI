import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { DevApp } from './DevApp';

it('labels the replaceable development shell', () => {
  render(<DevApp />);
  expect(screen.getByText(/Synthetic development entry point/)).toBeInTheDocument();
});
