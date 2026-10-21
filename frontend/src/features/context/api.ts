import type { InboxPreview } from './types';

export class PreviewError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

// Development-only fetch boundary; P5 will supply the shared client and auth context.
export async function loadInboxPreview(): Promise<InboxPreview> {
  const response = await fetch('/dev/p1/inbox');
  if (!response.ok) throw new PreviewError('Unable to load the synthetic Inbox.', response.status);
  const data: InboxPreview = await response.json();
  if (data.mode !== 'SYNTHETIC_FIXTURES' || !Array.isArray(data.records)) {
    throw new Error('Unexpected preview response. Check the P1 development backend.');
  }
  return data;
}
