import type { MessageAssociationRecord, OrderContextRecord, StoredMessage } from './types';

export const CANONICAL_TASK_TYPES = [
  'No progress after 2 follow-ups',
  'Follow-up limit reached',
  'No reply after reminder',
  'Identity or order link unclear',
  'Field conflict',
  'Commercial risk inquiry',
  'Knowledge gap or private data',
  'Processing failed',
  'Ambiguous customer reply',
  'Reply unavailable',
  'Supplier or customer unknown',
  'Low-confidence extraction',
] as const;

export type CanonicalTaskType = (typeof CANONICAL_TASK_TYPES)[number];

export interface TaskTypeConfig {
  type: CanonicalTaskType;
  reason: string;
  defaultPriority: 'LOW' | 'MEDIUM' | 'HIGH';
  actionsGuidance: string;
  badgeClass: 'danger' | 'amber' | 'blue' | 'purple' | 'gray';
}

export const TASK_TYPE_CONFIGS: Record<CanonicalTaskType, TaskTypeConfig> = {
  'No progress after 2 follow-ups': {
    type: 'No progress after 2 follow-ups',
    reason: 'Two consecutive clarification attempts completed without customer resolution.',
    defaultPriority: 'HIGH',
    actionsGuidance: 'Review customer response history, revise clarification terms, or forward for manager review.',
    badgeClass: 'danger',
  },
  'Follow-up limit reached': {
    type: 'Follow-up limit reached',
    reason: 'Maximum allowed follow-up attempts reached for this inquiry.',
    defaultPriority: 'HIGH',
    actionsGuidance: 'Review prior attempts, evaluate commercial terms manually, or mark unresolved.',
    badgeClass: 'danger',
  },
  'No reply after reminder': {
    type: 'No reply after reminder',
    reason: 'Customer reminder expired without receiving an inbound reply.',
    defaultPriority: 'MEDIUM',
    actionsGuidance: 'Check channel deliverability, trigger final reminder, or escalate to manager.',
    badgeClass: 'amber',
  },
  'Identity or order link unclear': {
    type: 'Identity or order link unclear',
    reason: 'Sender identity or candidate order link requires manual confirmation.',
    defaultPriority: 'HIGH',
    actionsGuidance: 'Inspect Identity & order tab to confirm verified customer or link to an existing order.',
    badgeClass: 'amber',
  },
  'Field conflict': {
    type: 'Field conflict',
    reason: 'Extracted values conflict with catalog specifications, standard units or delivery policies.',
    defaultPriority: 'HIGH',
    actionsGuidance: 'Compare source evidence in Review & Amend tab, amend conflicting fields with audit reason.',
    badgeClass: 'danger',
  },
  'Commercial risk inquiry': {
    type: 'Commercial risk inquiry',
    reason: 'Customer request contains non-standard pricing, discount, or delivery terms.',
    defaultPriority: 'HIGH',
    actionsGuidance: 'Verify terms with sales policy, request staff approval, or forward for manager review.',
    badgeClass: 'purple',
  },
  'Knowledge gap or private data': {
    type: 'Knowledge gap or private data',
    reason: 'Inquiry requires access to private customer account details or uncataloged terms.',
    defaultPriority: 'MEDIUM',
    actionsGuidance: 'Verify customer identity before sharing private details or draft clarification.',
    badgeClass: 'blue',
  },
  'Processing failed': {
    type: 'Processing failed',
    reason: 'Automated extraction pipeline failed or produced invalid structured data.',
    defaultPriority: 'HIGH',
    actionsGuidance: 'Use "Reprocess extraction" from More actions, or manually input fields supported by original text.',
    badgeClass: 'danger',
  },
  'Ambiguous customer reply': {
    type: 'Ambiguous customer reply',
    reason: 'Customer reply contains multiple interpretations or conflicting item references.',
    defaultPriority: 'MEDIUM',
    actionsGuidance: 'Send clarification update via Customer reply tab or amend supported quantities.',
    badgeClass: 'amber',
  },
  'Reply unavailable': {
    type: 'Reply unavailable',
    reason: 'Inbound channel does not support automated or authorized direct outbound replies.',
    defaultPriority: 'LOW',
    actionsGuidance: 'Check recipient preferences in Communication Center or contact via verified alternative channel.',
    badgeClass: 'gray',
  },
  'Supplier or customer unknown': {
    type: 'Supplier or customer unknown',
    reason: 'Sender or item catalog not recognized in active tenant master data.',
    defaultPriority: 'MEDIUM',
    actionsGuidance: 'Verify customer identity, link order candidate, or register inquiry in customer registry.',
    badgeClass: 'blue',
  },
  'Low-confidence extraction': {
    type: 'Low-confidence extraction',
    reason: 'One or more extracted fields are below confidence threshold or missing units/timezones.',
    defaultPriority: 'MEDIUM',
    actionsGuidance: 'Inspect highlighted evidence in original text, amend missing values, and record audit note.',
    badgeClass: 'blue',
  },
};

export function getTaskTypeConfig(type: CanonicalTaskType): TaskTypeConfig {
  return TASK_TYPE_CONFIGS[type] || TASK_TYPE_CONFIGS['Low-confidence extraction'];
}

export function toCanonicalTaskType(
  raw?: string,
  message?: StoredMessage | null,
  association?: MessageAssociationRecord | null,
  context?: OrderContextRecord | null
): CanonicalTaskType {
  if (raw && CANONICAL_TASK_TYPES.includes(raw as CanonicalTaskType)) {
    return raw as CanonicalTaskType;
  }
  if (raw) {
    const norm = raw.trim().toLowerCase();
    if (norm.includes('no progress') || norm.includes('2 follow-up') || norm === 'unresolved_clarification') {
      return 'No progress after 2 follow-ups';
    }
    if (norm.includes('limit reached')) return 'Follow-up limit reached';
    if (norm.includes('no reply') || norm.includes('reminder')) return 'No reply after reminder';
    if (norm.includes('identity') || norm.includes('order link') || norm === 'identity_conflict') {
      return 'Identity or order link unclear';
    }
    if (norm.includes('conflict') || norm === 'policy_conflict') return 'Field conflict';
    if (norm.includes('commercial') || norm === 'commercial_risk') return 'Commercial risk inquiry';
    if (norm.includes('knowledge') || norm.includes('private')) return 'Knowledge gap or private data';
    if (norm.includes('failed') || norm === 'failed_extraction' || norm === 'processing_failed') {
      return 'Processing failed';
    }
    if (norm.includes('ambiguous') || norm === 'ambiguity') return 'Ambiguous customer reply';
    if (norm.includes('reply unavailable') || norm.includes('unavailable')) return 'Reply unavailable';
    if (norm.includes('supplier') || norm.includes('unknown')) return 'Supplier or customer unknown';
    if (norm.includes('low-confidence') || norm.includes('extraction')) return 'Low-confidence extraction';
  }

  // Deduce from message, association and context if raw is not given
  if (message?.processing_status === 'PROCESSING_FAILED') {
    return 'Processing failed';
  }
  if (message?.processing_status === 'RECEIVED') {
    return 'Processing failed';
  }
  if (association && association.status !== 'LINK_VERIFIED') {
    return 'Identity or order link unclear';
  }
  if (context?.conflicts && context.conflicts.length > 0) {
    return 'Field conflict';
  }
  if (context?.status === 'CONFLICT') {
    return 'Field conflict';
  }
  if ((context?.status as string) === 'AMBIGUOUS' || context?.status === 'UNRESOLVED') {
    return 'Ambiguous customer reply';
  }
  if (context?.missing_fields && context.missing_fields.length > 0) {
    return 'Low-confidence extraction';
  }
  if (context?.status === 'INFORMATION_PARTIAL') {
    return 'Low-confidence extraction';
  }

  return 'Low-confidence extraction';
}
