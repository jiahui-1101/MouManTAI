import { useState } from 'react';
import { ConfirmationDialog } from '../../shared/ui';
import type { DecisionTerms, PreparedTerms } from './decisionTypes';
import { TermsComparison } from './DecisionTermsView';

function prepare(base: DecisionTerms | null | undefined, financial: boolean): PreparedTerms {
  return { lines: base?.lines.map(l => ({ ...l, unitPrice: financial ? l.unitPrice : null })) ?? [],
    price: financial ? base?.price : null, currency: financial ? base?.currency : null,
    fees: financial ? base?.fees : null, tax: financial ? base?.tax : null, discount: financial ? base?.discount : null,
    method: base?.method, deadline: base?.deadline, windowStart: base?.windowStart, location: base?.location,
    businessTimezone: base?.businessTimezone, instructions: base?.instructions, conditions: [...(base?.conditions ?? [])], policyRef: base?.policyRef };
}

/** Ephemeral, unsent comparison. No persistence, canonical hash, wire payload or command callback. */
export function ProposalPreparation({ base, financial, amendment = false }: { base?: DecisionTerms | null; financial: boolean; amendment?: boolean }) {
  const [draft, setDraft] = useState<PreparedTerms>(() => prepare(base, financial));
  const [reason, setReason] = useState('');
  const [discardOpen, setDiscardOpen] = useState(false);
  const mode = amendment ? 'amendment' : 'proposal';
  const input = (key: Exclude<keyof PreparedTerms, 'lines' | 'conditions'>, label: string) => <label>{label}
    <input value={draft[key] ?? ''} onChange={e => setDraft(current => ({ ...current, [key]: e.target.value }))} /></label>;
  const invalidQuantity = draft.lines.some(line => !/^\d+(?:\.\d+)?$/.test(line.quantity) || !/[1-9]/.test(line.quantity) || !line.sku.trim() || !line.unit.trim());
  const invalidMoney = financial && [draft.price, draft.fees, draft.tax, draft.discount, ...draft.lines.map(line => line.unitPrice)]
    .some(value => !!value && !/^\d+(?:\.\d+)?$/.test(value));
  return <details className="decision-preparation"><summary>Prepare an unsent {mode} comparison</summary>
    <p role="note">Local preparation only · not saved, submitted, priced, assessed or sent. Changing these fields does not change the original or confirmed agreement. It resets when the source/version/session refreshes or this page closes.</p>
    <form aria-label={`Unsent ${mode} preparation`} onSubmit={event => event.preventDefault()}>
      {draft.lines.map((line, i) => <fieldset key={i}><legend>Prepared line {i + 1}</legend>{(['sku', 'variant', 'quantity', 'unit', ...(financial ? ['unitPrice'] as const : [])] as const).map(key => <label key={key}>{`Line ${i + 1} ${key}`}
        <input value={line[key] ?? ''} onChange={e => setDraft(current => ({ ...current, lines: current.lines.map((item, j) => j === i ? { ...item, [key]: e.target.value } : item) }))} /></label>)}
        <button type="button" onClick={() => setDraft(current => ({ ...current, lines: current.lines.filter((_, j) => j !== i) }))}>Remove prepared line {i + 1}</button></fieldset>)}
      <button type="button" onClick={() => setDraft(current => ({ ...current, lines: [...current.lines, { sku: '', quantity: '', unit: '' }] }))}>Add prepared line</button>
      <div className="decision-fields">{financial && <>{input('price', 'Prepared binding price')}{input('currency', 'Prepared currency')}{input('fees', 'Prepared fees')}{input('tax', 'Prepared tax')}{input('discount', 'Prepared discount')}</>}
        {input('method', 'Prepared fulfilment method')}{input('windowStart', 'Prepared window start (explicit offset)')}{input('deadline', 'Prepared deadline (explicit offset)')}
        {input('businessTimezone', 'Prepared business timezone')}{input('location', 'Prepared location')}{input('instructions', 'Prepared special instructions')}{input('policyRef', 'Prepared policy reference')}
        <label>Prepared material conditions<textarea value={draft.conditions?.join('\n') ?? ''} onChange={e => setDraft(current => ({ ...current, conditions: e.target.value.split('\n') }))} /></label>
        <label>Reason for prepared changes<textarea value={reason} onChange={e => setReason(e.target.value)} /></label></div>
      {(invalidQuantity || invalidMoney) && <p role="status">Preparation has missing/invalid decimal quantities, units, SKUs or amounts. This is a display check, not backend validation.</p>}
      <button type="button" onClick={() => setDiscardOpen(true)}>Reset unsent preparation</button>
      <p>Submission unavailable: a verified versioned {mode} command and exact customer-assent contract are required.</p>
    </form>
    <TermsComparison original={base} proposed={draft} financial={financial}
      originalLabel={amendment ? 'Currently confirmed terms (preserved)' : 'Original customer request'} proposedLabel="Unsent local preparation" />
    <ConfirmationDialog open={discardOpen} onOpenChange={setDiscardOpen} title={`Discard unsent ${mode} preparation?`}
      description="This discards only your temporary comparison inputs. No backend terms, agreement, proposal or reservation will be changed."
      confirmLabel="Discard unsent preparation" onConfirm={() => { setDraft(prepare(base, financial)); setReason(''); setDiscardOpen(false); }} />
  </details>;
}
