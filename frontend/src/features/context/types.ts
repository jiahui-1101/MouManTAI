// PROVISIONAL P1 development OpenAPI types; P5 shared-contract review pending.
import type { components } from './generated/api';

export type RawMessageEnvelope = components['schemas']['RawMessageEnvelope'];
export type NormalizedMessage = components['schemas']['NormalizedMessage'];
export type ExtractedField = components['schemas']['ExtractedField'];
export type BusinessContext = components['schemas']['BusinessContext'];
export type ContextReview = components['schemas']['ContextReview'];
export type InboxRecord = components['schemas']['InboxRecord'];
export type InboxPreview = components['schemas']['InboxPreview'];
export type StoredMessage = components['schemas']['StoredMessage'];
export type MessagePage = components['schemas']['MessagePage'];
export type IngestResponse = components['schemas']['IngestResponse'];
export type DevelopmentContext = components['schemas']['DevelopmentContext'];
export type ExtractionAttemptRecord = components['schemas']['ExtractionAttemptRecord'];
export type ProcessResponse = components['schemas']['ProcessResponse'];
export type ExtractionHistoryResponse = components['schemas']['ExtractionHistoryResponse'];
export type FieldEvidence = components['schemas']['FieldEvidence'];
export type MessageAssociationRecord = components['schemas']['MessageAssociationRecord'];
export type AssociationCandidate = components['schemas']['AssociationCandidate'];
export type AssociationDecision = components['schemas']['AssociationDecision'];
export type AssociationDecisionRequest = components['schemas']['AssociationDecisionRequest'];
export type CustomerAccount = components['schemas']['CustomerAccount'];
export type OrderReference = components['schemas']['OrderReference'];

