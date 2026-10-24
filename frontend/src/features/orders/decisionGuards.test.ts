import { describe, expect, it } from 'vitest';
import { acceptanceBlockers, assentLabel, commandDependency, receiptLabel } from './decisionGuards';
import { decisionNow, decisionOrder, decisionSnapshot, offeredProposal } from './decisionTest.fixtures';

describe('Read-only decision safeguards', () => {
  it('never grants execution from a green badge or even a complete supplied snapshot', () => {
    expect(acceptanceBlockers(decisionOrder(), decisionSnapshot(), decisionNow)).toContain(commandDependency);
  });
  it.each(['missing-price', 'unknown-price', 'redacted-price', 'undisclosed', 'missing-hash', 'context-version', 'stale-snapshot', 'conditional', 'unknown-feasibility', 'identity', 'conflicting-field'])('explains %s without enabling a command', kind => {
    const d = decisionOrder(); const s = decisionSnapshot();
    if (kind === 'missing-price') s.exactOriginal!.price = null;
    if (kind === 'unknown-price') s.exactOriginal!.priceVerified = false;
    if (kind === 'redacted-price') s.financialAccess = 'REDACTED';
    if (kind === 'undisclosed') s.exactOriginal!.disclosed = false;
    if (kind === 'missing-hash') s.exactOriginal!.hash = null;
    if (kind === 'context-version') { d.version = undefined; d.contextVersion = '7'; }
    if (kind === 'stale-snapshot') d.assessment!.freshness = 'STALE';
    if (kind === 'conditional') d.assessment!.status = 'CONDITIONAL';
    if (kind === 'unknown-feasibility') d.assessment!.status = 'UNKNOWN';
    if (kind === 'identity') s.exactOriginal!.customerVerified = false;
    if (kind === 'conflicting-field') d.fields![0].status = 'CONFLICTING';
    expect(acceptanceBlockers(d, s, decisionNow).length).toBeGreaterThan(1);
    expect(acceptanceBlockers(d, s, decisionNow)).toContain(commandDependency);
  });
  it('requires evidence bound to exact proposal/version/hash/customer and time', () => {
    expect(assentLabel(offeredProposal(), decisionNow)).toMatch(/Source-reported exact assent evidence matches/);
  });
  it.each(['sent-only', 'version', 'hash', 'customer', 'unverified', 'no-evidence', 'legacy', 'future', 'no-expiry', 'expired', 'superseded'])('does not infer current agreement for %s', kind => {
    const p = offeredProposal();
    if (kind === 'sent-only') p.assent = undefined;
    if (kind === 'version') p.assent!.proposalVersion = '1';
    if (kind === 'hash') p.assent!.termsHash = 'another-hash';
    if (kind === 'customer') p.assent!.customerId = 'another-customer';
    if (kind === 'unverified') p.assent!.verified = false;
    if (kind === 'no-evidence') p.assent!.evidence = [];
    if (kind === 'legacy') p.terms.basis = 'LEGACY_CORE_TERMS';
    if (kind === 'future') p.assent!.at = '2026-10-25T02:00:00Z';
    if (kind === 'no-expiry') p.expiresAt = null;
    if (kind === 'expired') p.expiresAt = '2026-10-24T02:00:00Z';
    if (kind === 'superseded') p.superseded = true;
    expect(assentLabel(p, decisionNow)).not.toMatch(/^Source-reported exact assent evidence matches/);
  });
  it.each(['UNKNOWN', 'PENDING', 'FAILED'])('never turns %s receipt into accepted', outcome => {
    const text = receiptLabel({ id: 'receipt', orderId: 'order-one', outcome }, decisionSnapshot());
    expect(text).not.toMatch(/^Source records acceptance/);
    if (outcome !== 'FAILED') expect(text).toMatch(/do not resubmit/);
  });
  it('requires bound reservation and audit evidence even for a source ACCEPTED receipt', () => {
    const s = decisionSnapshot(); const r = { id: 'receipt', orderId: 'order-one', requestVersion: '7', termsHash: s.exactOriginal!.hash,
      outcome: 'ACCEPTED', auditRef: 'audit', reservationRef: 'reservation', reservationState: 'CONFIRMED', reservationVerified: true };
    expect(receiptLabel(r, s)).toMatch(/^Source records acceptance with a linked/);
    expect(receiptLabel({ ...r, reservationVerified: false }, s)).toMatch(/incomplete or unverified/);
    expect(receiptLabel({ ...r, requestVersion: '6' }, s)).toMatch(/incomplete or unverified/);
    expect(receiptLabel({ ...r, orderId: 'another-order' }, s)).toMatch(/incomplete or unverified/);
  });
});
