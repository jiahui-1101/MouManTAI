import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../../shared/auth';
import { OrderProgressPanel } from './OrderProgressPanel';
import { OrderDetailWorkspace } from './OrderDetailWorkspace';
import { decisionOrder, decisionSnapshot } from './decisionTest.fixtures';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const fact = (label: string) => screen.getByText(label, { selector: 'dt' }).closest('div')!;

it('keeps acceptance separate from missing agreement, reservation and fulfilment evidence', () => {
  const order = { ...decisionOrder(), status: 'ACCEPTED' };
  render(<OrderProgressPanel order={order} snapshot={{ ...decisionSnapshot(), currentAgreement: null, receipts: [] }} />);
  expect(fact('Order Acceptance')).toHaveTextContent('Source order lifecycle: ACCEPTED');
  expect(fact('Customer Agreement')).toHaveTextContent('Unavailable');
  expect(fact('Resource Reservation')).toHaveTextContent('Unavailable');
  expect(fact('Fulfilment')).toHaveTextContent('Unavailable');
});

it('does not promote a legacy agreement or synthetic record into accepted/reserved/delivered states', () => {
  const snapshot = decisionSnapshot(); snapshot.currentAgreement!.terms.basis = 'LEGACY_CORE_TERMS';
  render(<OrderProgressPanel order={decisionOrder()} snapshot={snapshot} />);
  expect(fact('Customer Agreement')).toHaveTextContent('LEGACY_CORE_TERMS');
  expect(fact('Customer Agreement')).toHaveTextContent('does not independently prove exact customer assent');
  expect(fact('Order Acceptance')).toHaveTextContent('PENDING_ACCEPTANCE');
  expect(fact('Resource Reservation')).toHaveTextContent('Unavailable');
  expect(fact('Fulfilment')).toHaveTextContent('Unavailable');
});

it('requires a matching complete reservation receipt rather than a bare reference or outcome', () => {
  const snapshot = decisionSnapshot(); snapshot.receipts = [{ id: 'receipt', orderId: 'order-one', requestVersion: '7', termsHash: 'test-backend-hash-original', outcome: 'ACCEPTED', reservationRef: 'reservation-1' }];
  const view = render(<OrderProgressPanel order={decisionOrder()} snapshot={snapshot} />);
  expect(fact('Resource Reservation')).toHaveTextContent('Unavailable');
  snapshot.receipts[0] = { ...snapshot.receipts[0], auditRef: 'audit-1', reservationVerified: true, reservationState: 'CONFIRMED' };
  view.rerender(<OrderProgressPanel order={decisionOrder()} snapshot={snapshot} />);
  expect(fact('Resource Reservation')).toHaveTextContent('Source-reported confirmed reservation reservation-1');
  expect(fact('Order Acceptance')).toHaveTextContent('PENDING_ACCEPTANCE');
  expect(fact('Fulfilment')).toHaveTextContent('Unavailable');
});

it.each(['order', 'tenant'])('withholds mismatched %s progress sources', kind => {
  const snapshot = decisionSnapshot(); if (kind === 'order') snapshot.orderId = 'foreign-order'; else snapshot.tenantId = 'foreign-tenant';
  render(<OrderProgressPanel order={decisionOrder()} snapshot={snapshot} />);
  expect(fact('Order Acceptance')).toHaveTextContent('Unavailable');
  expect(fact('Customer Agreement')).toHaveTextContent('Unavailable');
  expect(screen.queryByText(/Source agreement record/)).not.toBeInTheDocument();
});

it('shows explicitly linked Core fulfilment as a source report without converting it to trust or other progress', () => {
  const order = { ...decisionOrder(), commitmentId: 'linked-commitment' };
  const snapshot = decisionSnapshot(); snapshot.legacyFulfilment = { state: 'FULFILLED', commitmentId: 'linked-commitment', commitmentVersion: '4', evidence: ['synthetic-reference'] };
  render(<OrderProgressPanel order={order} snapshot={snapshot} />);
  expect(fact('Fulfilment')).toHaveTextContent('Core source state: FULFILLED');
  expect(fact('Fulfilment')).toHaveTextContent('not independent proof of real delivery');
  expect(fact('Order Acceptance')).toHaveTextContent('PENDING_ACCEPTANCE');
  expect(fact('Resource Reservation')).toHaveTextContent('Unavailable');
});

it('does not use a fulfilment record for another commitment', () => {
  const snapshot = decisionSnapshot(); snapshot.legacyFulfilment = { state: 'FULFILLED', commitmentId: 'foreign-commitment', commitmentVersion: '4', evidence: [] };
  render(<OrderProgressPanel order={{ ...decisionOrder(), commitmentId: 'current-commitment' }} snapshot={snapshot} />);
  expect(fact('Fulfilment')).toHaveTextContent('Unavailable');
});

it('puts real version comparison, unsent amendment preparation and persisted audit in History, sharing one read', async () => {
  const load = vi.fn().mockResolvedValue(decisionSnapshot()); const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  render(<QueryClientProvider client={new QueryClient()}><AuthProvider initialTenantId="tenant-one"><MemoryRouter>
    <OrderDetailWorkspace id="order-one" detail={decisionOrder()} now={Date.parse('2026-10-24T04:00:00Z')} busy={false} onRefresh={() => {}} state={null} legacy={<p>Legacy history source</p>} decisionSource={{ cacheKey: 'history-test-only', load }} />
  </MemoryRouter></AuthProvider></QueryClientProvider>);
  await screen.findByRole('region', { name: 'Acceptance review' });
  expect(screen.queryByRole('heading', { name: 'Order amendments · preserve confirmed terms' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'History' }));
  expect(await screen.findByRole('heading', { name: 'Order amendments · preserve confirmed terms' })).toBeVisible();
  const history = screen.getByRole('tabpanel', { name: 'History' });
  expect(within(history).getByRole('region', { name: 'Previous agreement version 3 versus Current agreement version 4' })).toHaveTextContent('110');
  expect(history).toHaveTextContent('source.terms_proposed'); expect(history).toHaveTextContent('synthetic-manager');
  expect(within(history).getByRole('button', { name: 'Submit amendment' })).toBeDisabled();
  fireEvent.click(within(history).getByText('Prepare an unsent amendment comparison'));
  expect(within(history).getByRole('form', { name: 'Unsent amendment preparation' })).toBeVisible();
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  expect(fetch).not.toHaveBeenCalled();
});

it('withholds a Core fulfilment projection when its commitment version conflicts with the current agreement', () => {
  const snapshot = decisionSnapshot(); snapshot.legacyFulfilment = { state: 'FULFILLED', commitmentId: 'current-commitment', commitmentVersion: '3', evidence: ['old-source'] };
  render(<OrderProgressPanel order={{ ...decisionOrder(), commitmentId: 'current-commitment' }} snapshot={snapshot} />);
  expect(fact('Fulfilment')).toHaveTextContent('Unavailable');
  expect(fact('Fulfilment')).not.toHaveTextContent('FULFILLED');
});
