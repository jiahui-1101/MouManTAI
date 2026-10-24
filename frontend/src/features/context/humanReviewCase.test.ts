import { describe, expect, it } from 'vitest';
import { determineHumanReviewCase } from './humanReviewCase';
import type { MessageAssociationRecord, OrderContextRecord, StoredMessage } from './types';

const message = { processing_status: 'PROCESSED' } as StoredMessage;
const association = { status: 'LINK_VERIFIED', verified_order: { order_id: 'order-1' } } as MessageAssociationRecord;
const context = { customer_identity_status: 'LINK_VERIFIED', status: 'INFORMATION_READY', missing_fields: [], conflicts: [] } as unknown as OrderContextRecord;

describe('human review case routing', () => {
  it('sends failed extraction and pending processing to message review', () => {
    expect(determineHumanReviewCase({ ...message, processing_status: 'PROCESSING_FAILED' }, association, context).kind).toBe('extraction_failed');
    expect(determineHumanReviewCase({ ...message, processing_status: 'PROCESSING' }, association, context).kind).toBe('processing_pending');
  });

  it('prioritizes identity and conflicting evidence before context acceptance', () => {
    expect(determineHumanReviewCase(message, null, context).kind).toBe('identity_review');
    expect(determineHumanReviewCase(message, { ...association, status: 'CONFLICT' }, context).kind).toBe('identity_review');
    expect(determineHumanReviewCase(message, association, { ...context, conflicts: ['date mismatch'] }).kind).toBe('context_conflict');
    expect(determineHumanReviewCase(message, association, { ...context, status: 'CONFLICT' }).kind).toBe('context_conflict');
  });

  it('separates missing information, ready information and an unlinked inquiry', () => {
    expect(determineHumanReviewCase(message, association, { ...context, status: 'INFORMATION_PARTIAL', missing_fields: ['unit'] }).kind).toBe('information_missing');
    expect(determineHumanReviewCase(message, association, context).canAcceptExtraction).toBe(true);
    expect(determineHumanReviewCase(message, association, null).canAcceptExtraction).toBe(false);
  });
});
