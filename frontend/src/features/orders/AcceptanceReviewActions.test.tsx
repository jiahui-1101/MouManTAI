import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { AcceptanceReviewActions } from './AcceptanceReviewActions';
import { ProposalPreparation } from './ProposalPreparation';
import { decisionOrder, decisionSnapshot, requestedTerms } from './decisionTest.fixtures';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('keeps acceptance disabled even for apparently complete synthetic terms and only permits read-only review', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  render(<AcceptanceReviewActions order={decisionOrder()} snapshot={decisionSnapshot()} />);
  for (const label of ['Accept as Requested', 'Accept Agreed Proposal']) expect(screen.getByRole('button', { name: label })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Review exact acceptance terms' }));
  const dialog = screen.getByRole('dialog', { name: 'Read-only acceptance terms review' });
  expect(dialog).toHaveTextContent('order-one'); expect(dialog).toHaveTextContent('Source request version: 7');
  expect(dialog).toHaveTextContent('20 pieces'); expect(dialog).toHaveTextContent('120');
  expect(dialog).toHaveTextContent('25 Oct 2026');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close review' }));
  expect(fetch).not.toHaveBeenCalled();
});

it('preserves redaction during term inspection and disables review when exact terms are absent', () => {
  const snapshot = decisionSnapshot(); snapshot.financialAccess = 'REDACTED';
  const view = render(<AcceptanceReviewActions order={decisionOrder()} snapshot={snapshot} />);
  fireEvent.click(screen.getByRole('button', { name: 'Review exact acceptance terms' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).queryByText('120')).not.toBeInTheDocument();
  expect(within(dialog).getAllByText('Redacted / unavailable').length).toBeGreaterThan(0);
  view.unmount(); render(<AcceptanceReviewActions order={decisionOrder()} snapshot={{ ...snapshot, exactOriginal: null }} />);
  expect(screen.getByRole('button', { name: 'Review exact acceptance terms' })).toBeDisabled();
});

it('reviews an unsent local proposal with provenance, then returns to editing without storage or network writes', () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); const storage = vi.spyOn(Storage.prototype, 'setItem');
  const base = requestedTerms(); const before = structuredClone(base);
  render(<ProposalPreparation base={base} financial />);
  fireEvent.click(screen.getByText('Prepare an unsent proposal comparison'));
  fireEvent.change(screen.getByLabelText('Line 1 quantity'), { target: { value: '25' } });
  fireEvent.change(screen.getByLabelText('Reason for prepared changes'), { target: { value: 'Source test adjustment' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review unsent proposal' }));
  const dialog = screen.getByRole('dialog', { name: 'Review unsent proposal' });
  expect(dialog).toHaveTextContent('Source request version: 7'); expect(dialog).toHaveTextContent('25 pieces');
  expect(dialog).toHaveTextContent('Source test adjustment');
  expect(dialog).toHaveTextContent('Submission is unavailable');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Keep editing' }));
  expect(screen.getByLabelText('Line 1 quantity')).toHaveValue('25');
  expect(fetch).not.toHaveBeenCalled(); expect(storage).not.toHaveBeenCalled(); expect(base).toEqual(before);
});

it('does not permit even a local review while quantity/date validation fails', () => {
  render(<ProposalPreparation base={requestedTerms()} financial />);
  fireEvent.click(screen.getByText('Prepare an unsent proposal comparison'));
  fireEvent.change(screen.getByLabelText('Prepared deadline (explicit offset)'), { target: { value: '2026-02-30T00:00:00Z' } });
  expect(screen.getByRole('button', { name: 'Review unsent proposal' })).toBeDisabled();
  expect(screen.getByLabelText('Preparation validation')).toHaveTextContent('real calendar date');
  fireEvent.click(screen.getByRole('button', { name: 'Remove prepared line 1' }));
  expect(screen.getByLabelText('Preparation validation')).toHaveTextContent('at least one prepared line');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
