import type { ExtractedField } from './types';

const labels: Record<string, string> = {
  sku: 'Product / SKU', quantity: 'Quantity', unit: 'Unit',
  requested_delivery_at: 'Requested delivery', order_id: 'Order reference',
  customer_id: 'Customer', special_instructions: 'Instructions',
};

export function FieldEvidence({ fields, timezone }: { fields: ExtractedField[]; timezone: string }) {
  return <section aria-labelledby="evidence-title" className="p1-evidence">
    <h3 id="evidence-title">Extracted fields <span className="p1-muted">& evidence</span></h3>
    <p className="p1-muted">Hand-labelled expected values · extraction has not run</p>
    {fields.length === 0 ? <p className="p1-notice">No grounded fields. Keep unresolved for manual review.</p> :
      <dl>{fields.map((field, index) => {
        const display = field.field_name === 'requested_delivery_at' && field.value
          ? new Intl.DateTimeFormat('en-MY', { timeZone: timezone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(field.value))
          : field.value;
        return <div className="p1-field" key={`${field.field_name}-${index}`}>
          <dt>{labels[field.field_name]} <span className={`p1-badge ${field.validation_status === 'VALID' ? 'p1-neutral' : 'p1-attention'}`}>{field.validation_status}</span></dt>
          <dd><strong>{display ?? 'Not provided'}</strong>
            {field.field_name === 'requested_delivery_at' && <small>{timezone} · requested, awaiting review</small>}
            {field.confidence != null && <small>Confidence: {Math.round(field.confidence * 100)}%</small>}
            {field.evidence?.map(evidence => <div className="p1-source" key={evidence.evidence_id}>
              <q>{evidence.quote}</q>
              <small>Source: {evidence.message_id} · characters {evidence.start}–{evidence.end} · {evidence.method} / {evidence.method_version}</small>
            </div>)}
            {field.corrected_by && <small>Corrected by: {field.corrected_by}</small>}
          </dd>
        </div>;
      })}</dl>}
  </section>;
}
