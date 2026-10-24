import { Link } from 'react-router-dom';
import { StatusBadge } from '../../shared/StatusBadge';
import type { OrderDetail } from './detailTypes';
import { shown, timestamp, profitText } from './queue';
import { assessmentState, evidenceAnchor, moneyText, quantityText, snapshotAge } from './detailView';
import { validDate } from './calendarDates';

function Values({ values, empty = 'Not available' }: { values?: string[]; empty?: string }) {
  return values?.length ? <ul>{values.map((value, i) => <li key={i}>{value}</li>)}</ul> : <p className="od-muted">{empty}</p>;
}
function Facts({ values }: { values: [string, string][] }) {
  return <dl className="od-facts">{values.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}

export function OrderSummaryPanel({ detail: d }: { detail: OrderDetail }) {
  return <section className="od-panel" aria-labelledby="od-summary"><h2 id="od-summary">Order summary</h2>
    <Facts values={[
      ['Order ID', d.id], ['Customer / source identifier', shown(d.customer)], ['Origin channel', shown(d.channel)],
      ['Original received', timestamp(d.receivedAt)], ['Information completed', timestamp(d.completedAt)],
      ['Order lifecycle', d.status?.trim() || 'UNKNOWN — no authoritative lifecycle provided'],
      ['Order request version', shown(d.version)], ['Original required deadline', timestamp(d.originalDeadline)],
      ['Current captured deadline', timestamp(d.currentDeadline)], ['Delivery / pickup', shown(d.fulfilment)],
      ['Authorized location', shown(d.location)], ['Customer special instructions', shown(d.instructions)],
      ['P1 context readiness (separate)', shown(d.contextStatus)], ['P1 context version (separate)', shown(d.contextVersion)],
      ['Context updated', timestamp(d.contextUpdatedAt)],
    ]} />
    <h3>Products and requested quantities</h3>{d.lines?.length ? <ul>{d.lines.map((line, i) => <li key={i}>
      Product: {shown(line.product)} · SKU: {shown(line.sku)} · {quantityText(line.quantity)}</li>)}</ul> : <p>Not available</p>}
  </section>;
}

export function CustomerRequestPanel({ detail: d }: { detail: OrderDetail }) {
  return <section className="od-panel" aria-labelledby="od-request"><h2 id="od-request">Customer request & source evidence</h2>
    <p>Customer statements and extracted values are distinct from verified operational availability.</p>
    <h3>Original message references</h3>{d.messages?.length ? <ul>{d.messages.map(message => <li key={message.id}>
      <a href={`#${evidenceAnchor(message.id)}`}>Read original message {message.id}</a></li>)}</ul> : <p>Original message evidence not available.</p>}
    {d.messages?.map(message => <article className="od-evidence" id={evidenceAnchor(message.id)} key={message.id} tabIndex={-1}>
      <h3>Message {message.id}</h3><p>{shown(message.tier)} · {shown(message.channel)} · {timestamp(message.receivedAt)}</p>
      <blockquote>{shown(message.text)}</blockquote></article>)}
    <h3>Structured fields and provenance</h3><p>Field status is source-supplied. Absent validation remains Not verified.</p>
    {d.fields?.length ? <div className="od-scroll" role="region" aria-label="Structured order fields, scroll horizontally" tabIndex={0}>
      <table><thead><tr><th scope="col">Field</th><th scope="col">Captured / corrected value</th><th scope="col">Validation</th><th scope="col">Evidence</th></tr></thead>
        <tbody>{d.fields.map((field, i) => <tr key={i}><th scope="row">{field.name}</th><td>{shown(field.value)}</td>
          <td>{['VALID', 'MISSING', 'AMBIGUOUS', 'CONFLICTING', 'UNVERIFIED'].includes(field.status ?? '') ? field.status : 'Not verified'}</td>
          <td>{field.evidence?.length ? <ul>{field.evidence.map((e, j) => <li key={j}>{e.ref}{e.quote && <blockquote>{e.quote}</blockquote>}</li>)}</ul> : 'Not verified'}</td></tr>)}</tbody></table></div> : <p>Structured fields not available.</p>}
    <h3>Source-reported conflicts</h3><Values values={d.fieldConflicts} empty="No conflict data supplied; this does not prove validity." />
    <a href="#legacy-order-context">Open existing P1 review, validation, versions and Core publishing</a>
  </section>;
}

export function FeasibilitySummary({ detail: d, now }: { detail: OrderDetail; now: number }) {
  const state = assessmentState(d, now); const a = d.assessment;
  const explanations: Record<string, string> = {
    FEASIBLE: 'Backend assessment reports feasibility only for the identified order version, snapshot and assumptions.',
    CONDITIONAL: 'Backend assessment depends on the stated conditions; unmet conditions still require verification.',
    INFEASIBLE: 'Backend assessment reports constraints preventing the assessed request.',
    UNKNOWN: 'Evidence, completeness, snapshot freshness or version authority is insufficient. Reassessment or verification is required.',
  };
  return <section className="od-panel od-assessment" aria-labelledby="od-feasibility"><h2 id="od-feasibility">Feasibility assessment</h2>
    <StatusBadge dimension="feasibility" state={state} /><p>{explanations[state]}</p>
    {!a && <p role="status">Pending-order assessment API unavailable. Legacy commitment assessments cannot substitute for this request.</p>}
    <Facts values={[
      ['Reported backend assessment', shown(a?.status)], ['Assessment ID / version', `${shown(a?.id)} / ${shown(a?.version)}`],
      ['Assessed order version', shown(a?.orderVersion)], ['Snapshot ID', shown(a?.snapshotId)],
      ['Snapshot timestamp', timestamp(a?.snapshotAt)], ['Snapshot age', snapshotAge(a?.snapshotAt, now)],
      ['Backend freshness verdict', a?.freshness ?? 'UNKNOWN'], ['Evidence verification', a?.sourceVerified ? 'Source-reported verified' : 'Not verified'],
      ['Assessment completeness', a?.complete ? 'Source-reported complete' : 'Incomplete / unknown'],
    ]} />
    <p className="od-notice">Assessment does not accept the order or reserve any stock, lot or capacity.</p>
  </section>;
}

export function InventoryAssessmentPanel({ detail: d }: { detail: OrderDetail }) {
  return <section className="od-panel" aria-labelledby="od-inventory"><h2 id="od-inventory">Inventory & materials</h2>
    <p>Backend quantities are shown with their own units. Incoming supply remains separate from stock on hand; no quantities are combined here.</p>
    {!d.materials?.length ? <p>Material availability cannot be verified: BOM, stock, lots and effective availability are not supplied.</p> :
      <div className="od-scroll" role="region" aria-label="Materials and lots, scroll horizontally" tabIndex={0}><table>
        <thead><tr>{['Material / BOM', 'Required / on hand', 'Effective / shortage', 'Lot / location / expiry', 'Incoming supply', 'Freshness / constraints'].map(h => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{d.materials.map((m, i) => <tr key={i}><th scope="row">{m.material}<small>BOM: {shown(m.bom)}</small></th>
          <td>Required: {quantityText(m.required)}<small>Stock on hand: {quantityText(m.onHand)}</small></td>
          <td>Effective availability (backend): {quantityText(m.effective)}<small>Shortage (backend): {quantityText(m.shortage)}</small></td>
          <td>{shown(m.lot)}<small>Location: {shown(m.location)}</small><small>Expiry: {validDate(m.expiresAt) ? `${m.expiresAt} (date only; cutoff unknown)` : timestamp(m.expiresAt)}</small><small>Relevance to deadline: Not verified</small></td>
          <td>{m.incoming?.length ? <ul>{m.incoming.map((s, j) => <li key={j}>{quantityText(s.quantity)} · {shown(s.status)}
            <small>Due: {timestamp(s.dueAt)}</small><Values values={s.evidence} empty="Supply evidence not available" /></li>)}</ul> : 'Not available'}</td>
          <td>{timestamp(m.sourceAt)}<Values values={m.constraints} /></td></tr>)}</tbody></table></div>}
    <h3>Existing reservations and separately reported demand</h3>
    <p>Accepted reservations require both source-reported ACCEPTED state and explicit reservation verification. Other rows are reported demand, not verified reservations.</p>
    {d.reservations?.length ? <ul>{d.reservations.map((r, i) => <li key={i}>
      <strong>{r.orderStatus === 'ACCEPTED' && r.verified === true ? 'Accepted reservation' : 'Reported demand — reservation not verified'}</strong>
      {' '}· {r.id} · <Link to={`/orders/${encodeURIComponent(r.orderId)}`}>{r.orderId}</Link> · {shown(r.orderStatus)}
      <small>{shown(r.resource)} · {quantityText(r.quantity)}</small><Values values={r.evidence} empty="Reservation evidence not available" /></li>)}</ul> : <p>Existing reservation records not available; no free stock is inferred.</p>}
  </section>;
}

export function CapacityAssessmentPanel({ detail: d }: { detail: OrderDetail }) {
  return <section className="od-panel" aria-labelledby="od-capacity"><h2 id="od-capacity">Capacity & schedule</h2>
    {!d.capacities?.length ? <p>Capacity, production windows, accepted workload and schedule conflicts cannot be verified.</p> : d.capacities.map((c, i) => <article className="od-evidence" key={i}>
      <h3>{c.resource}</h3><Facts values={[
        ['Required workload', quantityText(c.workload)], ['Available capacity (backend)', quantityText(c.available)],
        ['Production window start', timestamp(c.windowStart)], ['Production window end', timestamp(c.windowEnd)],
        ['Capacity gap', 'Unavailable — no source gap supplied'],
        ['Capacity source updated', timestamp(c.sourceAt)],
      ]} /><h4>Schedule / deadline conflicts</h4><Values values={c.conflicts} /><h4>Bottlenecks</h4><Values values={c.bottlenecks} />
      <h4>Time assumptions</h4><Values values={c.assumptions} /></article>)}
    <p>No frontend scheduler or free-capacity calculation is performed.</p>
  </section>;
}

export function PricingProvenancePanel({ detail: d }: { detail: OrderDetail }) {
  const p = d.pricing;
  if (!p || p.access !== 'AUTHORIZED') return <section className="od-panel" aria-labelledby="od-price"><h2 id="od-price">Pricing, costs & expected profit</h2>
    <p>{p?.access === 'REDACTED' ? 'Financial data redacted by source authorization.' : 'Financial authorization or source data not available. Expected profit unknown.'}</p></section>;
  return <section className="od-panel" aria-labelledby="od-price"><h2 id="od-price">Pricing, costs & expected profit</h2>
    <Facts values={[
      ['Customer-offered price (claim)', moneyText(p.customerPrice, p.currency)], ['Authorized quote (source-reported)', p.sourceVerified ? moneyText(p.quotedPrice, p.currency) : 'Not verified'],
      ['Approved price source', shown(p.priceSource)], ['Quote / price version', shown(p.quoteVersion)],
      ['Price disclosed', shown(p.disclosed)], ['Price agreed', shown(p.agreed)],
      ['Financial source updated', timestamp(p.sourceAt)], ['Cost provenance', shown(p.costSource)],
      ['Expected profit', p.sourceVerified && !p.missingCosts?.length ? profitText({ amount: p.profit, currency: p.currency,
        costComplete: p.costComplete, priceSource: p.priceSource, costSource: p.costSource }) : 'Not verified / cost incomplete — expected profit unavailable'],
    ]} />
    <h3>Cost components (no frontend totals)</h3>{p.costs?.length ? <ul>{p.costs.map((c, i) => <li key={i}>{c.component}: {moneyText(c.amount, p.currency)} · {shown(c.source)}</li>)}</ul> : <p>BOM/material, inventory valuation, labour and delivery cost coverage not available.</p>}
    <h3>Missing cost components</h3><Values values={p.missingCosts} empty={p.costComplete ? 'Source reports complete coverage.' : 'Coverage unknown / incomplete.'} />
  </section>;
}

export function DecisionReadinessPanel({ detail: d, now }: { detail: OrderDetail; now: number }) {
  const a = d.assessment;
  return <section className="od-panel" aria-labelledby="od-decision"><h2 id="od-decision">Recommendation & decision readiness · read only</h2>
    <p>Backend recommendation: {shown(a?.recommendation)}</p>
    {assessmentState(d, now) === 'UNKNOWN' && <p className="od-notice">Assessment is not current and verified for this order version. Do not treat this recommendation as approval.</p>}
    {([['Reasons', a?.reasons], ['Hard constraints', a?.constraints], ['Soft preferences', a?.preferences], ['Blocking factors', a?.blockers],
      ['Outstanding conditions', a?.conditions], ['Assumptions', a?.assumptions], ['Assessment evidence references', a?.evidence], ['Missing evidence', a?.missingEvidence]] as [string, string[] | undefined][])
      .map(([label, values]) => <div key={label}><h3>{label}</h3><Values values={values} /></div>)}
    <p>Decision commands remain unavailable until verified backend integration. The Order Decision workspace below separates exact terms, proposals, amendments and recorded outcomes; frontend assessment does not grant execution authority.</p>
    {d.commitmentId && <p>Explicit P1-linked commitment: <Link to={`/commitments/${encodeURIComponent(d.commitmentId)}`}>{d.commitmentId}</Link> (existing commitment workflow; not a pending-order assessment).</p>}
  </section>;
}
