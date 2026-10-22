import type { OrderContextRecord } from './types';

export function reviewCandidates(context: OrderContextRecord) {
  return Object.entries(context.field_evidence ?? {}).flatMap(([field, values]) => {
    if (!['sku', 'quantity', 'unit', 'requested_delivery_at'].includes(field) || !Array.isArray(values)) return [];
    return values.flatMap((ev, index) => {
      if (ev.method !== 'MODEL' && ev.validation_status !== 'UNRESOLVED') return [];
      const metadata = ev.normalization_metadata as Record<string, unknown> | undefined;
      const value = String(ev.normalized_value ?? ev.quote ?? '');
      if (!value) return [];
      return [{ field, value, quote: String(ev.quote ?? ''), method: String(ev.method ?? 'MODEL'),
        source: String(ev.message_id ?? ''), start: ev.start, end: ev.end,
        group: String(metadata?.group_id ?? ev.group_id ?? ''),
        unverifiedProduct: field === 'sku' && metadata?.domain_supported !== 'true',
        key: `${field}:${ev.evidence_id ?? index}:${index}` }];
    });
  });
}
