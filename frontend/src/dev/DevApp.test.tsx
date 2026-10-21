import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { DevApp } from './DevApp';

it('labels the replaceable development shell', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockReturnValue(new Promise(() => {}));
  render(<DevApp />);
  expect(screen.getByText(/Synthetic development entry point/)).toBeInTheDocument();
  fetcher.mockRestore();
});
