import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { ProposalPreparation } from './ProposalPreparation';
import { requestedTerms } from './decisionTest.fixtures';
import type { DecisionTerms } from './decisionTypes';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function setup(base: DecisionTerms | undefined = requestedTerms(), financial = true, amendment = false) {
  render(<ProposalPreparation base={base} financial={financial} amendment={amendment} />);
  fireEvent.click(screen.getByText(`Prepare an unsent ${amendment ? 'amendment' : 'proposal'} comparison`));
  return screen.getByRole('form', { name: `Unsent ${amendment ? 'amendment' : 'proposal'} preparation` });
}
const change = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const startLabel = 'Prepared window start (explicit offset)', endLabel = 'Prepared deadline (explicit offset)';
const feedback = () => screen.getByRole('status', { name: 'Preparation validation' });

describe('Unsent preparation input validation', () => {
  it.each([false, true])('warns after removing every line, supports correction and keeps %s amendment mode unsent', amendment => {
    const base = requestedTerms(), before = structuredClone(base);
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch); const storage = vi.spyOn(Storage.prototype, 'setItem');
    const form = setup(base, true, amendment);
    fireEvent.click(screen.getByRole('button', { name: 'Remove prepared line 1' }));
    expect(feedback()).toHaveTextContent('Add at least one prepared line');
    expect(form).toHaveAttribute('aria-describedby', feedback().id);
    fireEvent.click(screen.getByRole('button', { name: 'Add prepared line' }));
    expect(feedback()).toHaveTextContent('positive decimal quantity');
    for (const [label, value] of [['Line 1 sku', 'BREAD'], ['Line 1 unit', 'pieces'], ['Line 1 quantity', '0.5']]) change(label, value);
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
    fireEvent.submit(form);
    expect(form).toHaveTextContent('Submission unavailable');
    expect(screen.queryByRole('button', { name: /^(Submit|Accept|Send|Reserve)/ })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled(); expect(storage).not.toHaveBeenCalled(); expect(base).toEqual(before);
  });
  it('warns when an original source has no prepared lines', () => {
    const base = requestedTerms(); base.lines = []; setup(base);
    expect(feedback()).toHaveTextContent('Add at least one prepared line');
  });
  it.each(['', '0', '0.00', '-1', '1e3', 'NaN', '1.2.3'])('retains positive-decimal quantity validation for %s', value => {
    setup(); change('Line 1 quantity', value); expect(feedback()).toHaveTextContent('positive decimal quantity');
  });
  it.each(['Line 1 sku', 'Line 1 unit'])('retains non-empty validation for %s', label => {
    setup(); change(label, ' '); expect(feedback()).toHaveTextContent('non-empty SKU and unit');
  });
  it.each(['Prepared binding price', 'Prepared fees', 'Prepared tax', 'Prepared discount', 'Line 1 unitPrice'])('retains monetary validation for %s', label => {
    setup(); change(label, '-1'); expect(feedback()).toHaveTextContent('non-negative decimal amounts');
    change(label, '1e3'); expect(feedback()).toHaveTextContent('non-negative decimal amounts');
    change(label, '0.00'); expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
    change(label, ''); expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
  });
  it.each([
    '2026-02-29T10:00:00Z', '2024-02-30T10:00:00Z', '1900-02-29T10:00:00Z',
    '2026-13-01T10:00:00Z', '2026-04-31T10:00:00Z', '2026-01-00T10:00:00Z',
    '2026-10-25', '2026-10-25T10:00:00', '2026-10-25T10:00Z',
    '2026-10-25T24:00:00Z', '2026-10-25T10:60:00Z', '2026-10-25T10:00:60Z',
    '2026-10-25T10:00:00+24:00', '2026-10-25T10:00:00+08:60',
    '2026-10-25T10:00:00-24:00', '2026-10-25T10:00:00-05:99',
    '2026-10-25T10:00:00+0800', 'not-a-date',
  ])('rejects invalid calendar/time/offset input %s without assuming a date-only midnight', value => {
    setup(); change(endLabel, value);
    expect(feedback()).toHaveTextContent('Prepared deadline must contain a real calendar date');
    const input = screen.getByLabelText(endLabel);
    expect(input).toHaveValue(value); expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAttribute('aria-describedby', feedback().id);
  });
  it('validates the optional start independently and clears feedback when corrected', () => {
    setup(); change(startLabel, '2026-02-29T01:00:00+08:00');
    expect(feedback()).toHaveTextContent('Prepared window start must contain a real calendar date');
    expect(screen.getByLabelText(startLabel)).toHaveAttribute('aria-invalid', 'true');
    change(startLabel, '2024-02-29T01:00:00+08:00');
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
    expect(screen.getByLabelText(startLabel)).not.toHaveAttribute('aria-invalid');
  });
  it.each(['2024-02-29T10:00:00Z', '2000-02-29T10:00:00+08:00', '2024-02-29T23:30:00-05:00'])('accepts real leap-date instants with explicit offsets: %s', value => {
    const base = requestedTerms(), before = structuredClone(base); setup(base); change(endLabel, value);
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
    expect(screen.getByLabelText(endLabel)).toHaveValue(value); expect(base).toEqual(before);
  });
  it.each([
    ['2026-10-25T09:00:00Z', '2026-10-25T08:00:00Z'],
    ['2026-10-25T10:00:00+08:00', '2026-10-25T03:00:00+02:00'],
  ])('rejects reversed windows by actual instants: %s / %s', (start, end) => {
    setup(); change(startLabel, start); change(endLabel, end);
    expect(feedback()).toHaveTextContent('must not be after the deadline / window end');
    expect(screen.getByLabelText(startLabel)).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText(endLabel)).toHaveAttribute('aria-invalid', 'true');
  });
  it.each([
    ['2026-10-25T10:00:00+08:00', '2026-10-25T03:00:00Z'],
    ['2026-10-25T10:00:00+08:00', '2026-10-25T02:00:00Z'],
    ['2026-10-24T23:30:00-05:00', '2026-10-25T05:00:00Z'],
  ])('preserves ordered/equal windows without inventing duration rules: %s / %s', (start, end) => {
    setup(); change(startLabel, start); change(endLabel, end);
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
  });
  it('keeps absent optional times/timezone/money optional and validates only provided values', () => {
    const base = requestedTerms(); delete base.windowStart; base.deadline = null; base.businessTimezone = undefined;
    base.price = null; base.fees = ''; base.tax = undefined; base.discount = null;
    setup(base); expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
    change(startLabel, '2024-02-29T10:00:00Z');
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
    change(startLabel, ''); change(endLabel, '2024-02-29T12:00:00Z');
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
  });
  it('validates only supplied timezone text without changing the explicit offset or inventing a timezone match policy', () => {
    setup(); change('Prepared business timezone', 'Not/A_Zone');
    expect(feedback()).toHaveTextContent('Prepared business timezone is not recognized');
    expect(screen.getByLabelText('Prepared business timezone')).toHaveAttribute('aria-invalid', 'true');
    for (const zone of ['Asia/Kuala_Lumpur', 'America/New_York', 'UTC', '']) {
      change('Prepared business timezone', zone);
      expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
    }
  });
  it('keeps hidden financial inputs excluded from validation and display', () => {
    const base = requestedTerms(); base.price = '-private-price'; base.lines[0].unitPrice = '-private-unit-price';
    setup(base, false); expect(screen.queryByLabelText('Prepared binding price')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('private-price');
    expect(document.body).not.toHaveTextContent('private-unit-price');
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
  });
  it('resets invalid local input and validation feedback through the existing discard confirmation', () => {
    const form = setup(); change(endLabel, '2026-02-30T00:00:00Z');
    expect(feedback()).toBeInTheDocument(); fireEvent.click(within(form).getByRole('button', { name: 'Reset unsent preparation' }));
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsent preparation' }));
    expect(screen.getByLabelText(endLabel)).toHaveValue(requestedTerms().deadline);
    expect(screen.queryByRole('status', { name: 'Preparation validation' })).not.toBeInTheDocument();
  });
});
