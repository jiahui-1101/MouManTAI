import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SyntheticComposer } from './SyntheticComposer';

describe('explicit synthetic timezone', () => {
  it('sends null when operator declares missing timezone and freezes it for retry', async () => {
    const ingest = vi.fn().mockRejectedValue(new Error('offline'));
    render(<SyntheticComposer tenantId="synthetic_tenant_a" ingest={ingest} onSuccess={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Synthetic business timezone'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Original message text'), { target: { value: 'Need 15 burgers tomorrow' } });
    fireEvent.submit(screen.getByLabelText('Original message text').closest('form')!);
    await waitFor(() => expect(ingest).toHaveBeenCalledTimes(1));
    expect(ingest.mock.calls[0][0].business_timezone).toBeNull();
    expect(ingest.mock.calls[0][0].received_at).toBe(ingest.mock.calls[0][0].message_at);
  });
});
