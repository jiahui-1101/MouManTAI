import type { MessageAssociationRecord, OrderContextRecord, StoredMessage } from './types';

export type HumanReviewCaseKind =
  | 'extraction_failed'
  | 'processing_pending'
  | 'identity_review'
  | 'context_conflict'
  | 'information_missing'
  | 'information_ready'
  | 'inquiry_or_unlinked';

export interface HumanReviewCase {
  kind: HumanReviewCaseKind;
  title: string;
  nextStep: string;
  canAcceptExtraction: boolean;
}

/** Classify only states exposed by the current message, association and context APIs. */
export function determineHumanReviewCase(
  message: StoredMessage | null,
  association: MessageAssociationRecord | null,
  context: OrderContextRecord | null,
): HumanReviewCase {
  if (message?.processing_status === 'PROCESSING_FAILED') return {
    kind: 'extraction_failed', title: 'Extraction needs attention',
    nextStep: 'Inspect the processing evidence and retry extraction from Customer Messages before deciding the order context.',
    canAcceptExtraction: false,
  };
  if (message?.processing_status === 'RECEIVED' || message?.processing_status === 'PROCESSING') return {
    kind: 'processing_pending', title: 'Message processing is incomplete',
    nextStep: 'Wait for processing or run extraction from Customer Messages. Do not approve fields that have not been checked.',
    canAcceptExtraction: false,
  };
  if (!association || association.status !== 'LINK_VERIFIED' || (context && context.customer_identity_status !== 'LINK_VERIFIED')) return {
    kind: 'identity_review', title: 'Identity or order link needs verification',
    nextStep: 'Verify the sender and order association in Customer Messages. Keep customer-specific information private until linkage is confirmed.',
    canAcceptExtraction: false,
  };
  if (context?.conflicts?.length || context?.status === 'CONFLICT') return {
    kind: 'context_conflict', title: 'Conflicting order information',
    nextStep: 'Compare the original evidence, correct supported fields, and record a reason. Keep unresolved terms out of acceptance.',
    canAcceptExtraction: false,
  };
  if (context?.missing_fields?.length || context?.status === 'INFORMATION_PARTIAL' || context?.status === 'UNRESOLVED') return {
    kind: 'information_missing', title: 'Customer information is incomplete',
    nextStep: 'Correct fields supported by evidence, or record that more information is needed. Recording the need does not send a message.',
    canAcceptExtraction: false,
  };
  if (context?.status === 'INFORMATION_READY') return {
    kind: 'information_ready', title: 'Information ready for order decision',
    nextStep: 'Confirm the extracted information. Order acceptance and resource reservation remain separate SME decisions.',
    canAcceptExtraction: true,
  };
  return {
    kind: 'inquiry_or_unlinked', title: 'Inquiry needs a supported review route',
    nextStep: 'Inspect the original message. A verified order context is required for context review; a customer reply requires an authorized reply and channel route.',
    canAcceptExtraction: false,
  };
}

export * from './taskTypes';

