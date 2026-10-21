import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import catalog from '../../../../backend/app/context/fixtures/scenarios.json';
import { PreviewError, loadInboxPreview } from './api';
import { Inbox } from './Inbox';
import type { InboxPreview } from './types';

// JSON literals widen to strings; backend fixture tests validate this exact file against Pydantic.
const data = { mode: catalog.mode, business_timezone: catalog.business_timezone, records: catalog.records } as unknown as InboxPreview;

describe('fixture Inbox', () => {
  it('shows loading, source evidence and four independent state dimensions', async () => {
    render(<Inbox load={async () => data} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
    const detail = await screen.findByRole('region', { name: 'Message details' });
    expect(within(detail).getByText('Processing')).toBeInTheDocument();
    expect(within(detail).getByText('Information')).toBeInTheDocument();
    expect(within(detail).getByText('Identity')).toBeInTheDocument();
    expect(within(detail).getByText('Review')).toBeInTheDocument();
    expect(within(detail).getByText('tomorrow before 3pm')).toBeInTheDocument();
    expect(within(detail).getByText(/characters 7–10/)).toBeInTheDocument();
    expect(within(detail).getByText(/21 Oct 2026/)).toBeInTheDocument();
    expect(screen.getByText(/extraction has not run/)).toBeInTheDocument();
  });

  it('filters channels, searches and shows empty results', async () => {
    render(<Inbox load={async () => data} />);
    await screen.findByText('9 examples');
    fireEvent.click(screen.getByRole('button', { name: 'Email' }));
    expect(screen.getByText('2 examples')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Email' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search messages' }), { target: { value: 'nonexistent' } });
    expect(screen.getByRole('status')).toHaveTextContent('No messages');
  });

  it('shows ambiguity without asserting an order link', async () => {
    render(<Inbox load={async () => data} />);
    fireEvent.click(await screen.findByRole('button', { name: /Several possible orders/ }));
    const detail = screen.getByRole('region', { name: 'Message details' });
    expect(within(detail).getByText('AMBIGUOUS')).toBeInTheDocument();
    expect(within(detail).getByText(/Expected order: Unlinked/)).toBeInTheDocument();
    expect(within(detail).getByText(/No grounded fields/)).toBeInTheDocument();
    expect(within(detail).queryByRole('button', { name: /link|accept/i })).not.toBeInTheDocument();
  });

  it('keeps proposed confirmed-term conflicts visible', async () => {
    render(<Inbox load={async () => data} />);
    fireEvent.click(await screen.findByRole('button', { name: /Change to confirmed terms/ }));
    expect(screen.getByText(/Quantity differs from confirmed 80 pcs/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Message details' })).getByText('CONFLICT')).toBeInTheDocument();
  });

  it('supports empty datasets', async () => {
    render(<Inbox load={async () => ({ ...data, records: [] })} />);
    expect(await screen.findByText('No messages match this view.')).toBeInTheDocument();
  });

  it('reports failed loads and retries successfully', async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error('Backend offline')).mockResolvedValueOnce(data);
    render(<Inbox load={load} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Backend offline');
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading' }));
    expect(await screen.findByText('9 examples')).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('distinguishes permission errors', async () => {
    render(<Inbox load={async () => { throw new PreviewError('Fixture permission example', 403); }} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Access denied');
  });

  it('loads only the explicit development API and rejects unexpected responses', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify(data)));
    try {
      expect((await loadInboxPreview()).mode).toBe('SYNTHETIC_FIXTURES');
      expect(fetcher).toHaveBeenCalledWith('/dev/p1/inbox');
      fetcher.mockResolvedValueOnce(new Response('{}'));
      await expect(loadInboxPreview()).rejects.toThrow('Unexpected preview response');
      fetcher.mockResolvedValueOnce(new Response('', { status: 503 }));
      await expect(loadInboxPreview()).rejects.toMatchObject({ status: 503 });
    } finally { fetcher.mockRestore(); }
  });
});
