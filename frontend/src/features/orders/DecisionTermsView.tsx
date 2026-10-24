import type { DecisionTerms, PreparedTerms } from './decisionTypes';
import { shown, timestamp } from './queue';

export function termsRows(t: Partial<DecisionTerms> | PreparedTerms | null | undefined, financial: boolean): [string, string][] {
  const price = (value: string | null | undefined) => financial ? shown(value) : 'Redacted / unavailable';
  return [
    ['Products / variants / quantities / units', t?.lines?.map(l => `${l.sku} [${l.variant ?? 'variant not provided'}] · ${l.quantity} ${l.unit}${financial ? ` · unit price ${shown(l.unitPrice)}` : ''}`).join('\n') || 'Not available'],
    ['Binding price', price(t?.price)], ['Currency', price(t?.currency)], ['Fees', price(t?.fees)], ['Tax', price(t?.tax)], ['Discount', price(t?.discount)],
    ['Fulfilment method', shown(t?.method)], ['Window start', timestamp(t?.windowStart)], ['Deadline / window end', timestamp(t?.deadline)],
    ['Business timezone', shown(t?.businessTimezone)], ['Location', shown(t?.location)], ['Special instructions', shown(t?.instructions)],
    ['Material conditions', t?.conditions?.join('\n') || 'Not available'], ['Binding policy reference', shown(t?.policyRef)],
  ];
}

export function DecisionTermsView({ terms: t, title, financial }: { terms?: DecisionTerms | null; title: string; financial: boolean }) {
  return <section className="decision-terms"><h3>{title}</h3>{!t ? <p>Exact terms not available. Captured context fields are not a complete customer offer.</p> : <>
    <p>Terms source: {t.basis}. {t.basis === 'LEGACY_CORE_TERMS' && 'Legacy confirmed terms lack the v2.2 commercial/hash/assent contract.'}</p>
    <p>Customer identity: {shown(t.customerId)} · {t.customerVerified ? 'source-reported verified' : 'not verified for exact terms'}</p>
    <p>Request version: {shown(t.requestVersion)} · Terms revision: {shown(t.revision)} · Backend terms hash: {shown(t.hash)}</p>
    <dl>{termsRows(t, financial).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    <p>Price source/version: {financial ? `${shown(t.priceSource)} / ${shown(t.priceSourceVersion)}` : 'Redacted / unavailable'}</p>
    <p>Price disclosure: {financial ? t.disclosed === true ? 'Source reports disclosed' : 'Not verified' : 'Redacted / unavailable'}</p>
    <p>Source evidence: {t.evidence?.join(', ') || 'Not available'}</p>
  </>}</section>;
}

export function TermsComparison({ original, proposed, financial, originalLabel = 'Original customer request', proposedLabel = 'Proposed terms' }: {
  original?: DecisionTerms | null; proposed?: DecisionTerms | PreparedTerms | null; financial: boolean; originalLabel?: string; proposedLabel?: string;
}) {
  const left = termsRows(original, financial); const right = termsRows(proposed, financial);
  return <div className="decision-scroll" role="region" aria-label={`${originalLabel} versus ${proposedLabel}`} tabIndex={0}>
    <table><caption>Display comparison only · no canonical equality or assent is calculated</caption><thead><tr><th scope="col">Term</th><th scope="col">{originalLabel}</th>
      <th scope="col">{proposedLabel}</th><th scope="col">Display difference</th></tr></thead><tbody>{left.map(([label, value], i) => {
        const next = right[i][1]; const unknown = [value, next].some(v => ['Not available', 'Redacted / unavailable'].includes(v));
        return <tr key={label} className={!unknown && value !== next ? 'decision-changed' : ''}><th scope="row">{label}</th><td>{value}</td><td>{next}</td>
          <td>{unknown ? 'Not verified' : value === next ? 'Same displayed value' : 'Changed displayed value'}</td></tr>;
      })}</tbody></table></div>;
}
