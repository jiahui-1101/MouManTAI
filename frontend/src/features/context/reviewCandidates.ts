import type { OrderContextRecord } from './types';

export interface EvidenceItemGroup {
  groupId: string;
  validSku: string;
  unverifiedProduct: string;
  productQuote: string;
  quantity: string;
  unit: string;
  start?: number;
  end?: number;
  method: string;
}

export function extractEvidenceItemGroups(context: OrderContextRecord): EvidenceItemGroup[] {
  const groups = new Map<string, EvidenceItemGroup>();
  const ensureGroup = (gid: string): EvidenceItemGroup => {
    const key = gid || 'g1';
    let grp = groups.get(key);
    if (!grp) {
      grp = {
        groupId: key,
        validSku: '',
        unverifiedProduct: '',
        productQuote: '',
        quantity: '',
        unit: '',
        method: '',
      };
      groups.set(key, grp);
    }
    return grp;
  };

  for (const field of ['sku', 'quantity', 'unit'] as const) {
    const evList = context.field_evidence?.[field];
    if (!Array.isArray(evList)) continue;
    evList.forEach((ev, idx) => {
      const metadata = ev.normalization_metadata as Record<string, unknown> | undefined;
      const explicitGid = metadata?.group_id ?? ev.group_id;
      const existingKeys = Array.from(groups.keys());
      const fallbackGid = existingKeys[idx] ?? (evList.length > 1 ? `g${idx + 1}` : existingKeys[0] ?? 'g1');
      const gid = String(explicitGid ?? fallbackGid);
      const grp = ensureGroup(gid);
      const val = String(ev.normalized_value ?? ev.quote ?? '');
      if (field === 'sku') {
        const isSupported = ev.validation_status === 'VALID' && metadata?.domain_supported !== 'false';
        if (isSupported && val) {
          grp.validSku = val;
        } else if (val) {
          grp.unverifiedProduct = val;
        }
        grp.productQuote = String(ev.quote ?? val ?? '');
        grp.start = typeof ev.start === 'number' ? ev.start : undefined;
        grp.end = typeof ev.end === 'number' ? ev.end : undefined;
        grp.method = String(ev.method ?? '');
      } else if (field === 'quantity' && val && !grp.quantity) {
        grp.quantity = val;
        if (!grp.method) grp.method = String(ev.method ?? '');
      } else if (field === 'unit' && val && !grp.unit) {
        grp.unit = val;
      }
    });
  }

  return Array.from(groups.values()).filter(
    g => Boolean(g.validSku || g.unverifiedProduct || g.quantity || g.unit)
  );
}

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
