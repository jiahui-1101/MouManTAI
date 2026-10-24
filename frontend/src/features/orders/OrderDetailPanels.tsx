import { Link } from 'react-router-dom';
import { StatusBadge } from '../../shared/StatusBadge';
import type { OrderDetail } from './detailTypes';
import { shown, timestamp, profitText } from './queue';
import { assessmentState, evidenceAnchor, moneyText, quantityText, snapshotAge } from './detailView';
import { validDate } from './calendarDates';

function Values({ values, empty = 'Not available' }: { values?: string[]; empty?: string }) {
  return values?.length ? (
    <ul className="od-bullet-list">
      {values.map((value, i) => (
        <li key={i}>{value}</li>
      ))}
    </ul>
  ) : (
    <p className="od-muted">{empty}</p>
  );
}

function Facts({ values }: { values: [string, string][] }) {
  return (
    <dl className="od-facts">
      {values.map(([label, value]) => (
        <div key={label} className="od-fact-item">
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function OrderSummaryPanel({ detail: d }: { detail: OrderDetail }) {
  return (
    <section className="od-panel" aria-labelledby="od-summary">
      <div className="od-panel-header">
        <h2 id="od-summary">Order summary</h2>
        {d.status && <span className="od-badge-lifecycle">{d.status}</span>}
      </div>

      <Facts
        values={[
          ['Order ID', d.id],
          ['Customer / source identifier', shown(d.customer)],
          ['Origin channel', shown(d.channel)],
          ['Original received', timestamp(d.receivedAt)],
          ['Information completed', timestamp(d.completedAt)],
          ['Order lifecycle', d.status?.trim() || 'UNKNOWN — no authoritative lifecycle provided'],
          ['Order request version', shown(d.version)],
          ['Original required deadline', timestamp(d.originalDeadline)],
          ['Current captured deadline', timestamp(d.currentDeadline)],
          ['Delivery / pickup', shown(d.fulfilment)],
          ['Authorized location', shown(d.location)],
          ['Customer special instructions', shown(d.instructions)],
          ['P1 context readiness (separate)', shown(d.contextStatus)],
          ['P1 context version (separate)', shown(d.contextVersion)],
          ['Context updated', timestamp(d.contextUpdatedAt)],
        ]}
      />

      <div className="od-sub-section">
        <h3>Products and requested quantities</h3>
        {d.lines?.length ? (
          <ul className="od-items-list">
            {d.lines.map((line, i) => (
              <li key={i} className="od-item-row">
                Product: {shown(line.product)} · SKU: {shown(line.sku)} · {quantityText(line.quantity)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="od-muted">Not available</p>
        )}
      </div>
    </section>
  );
}

export function CustomerRequestPanel({ detail: d }: { detail: OrderDetail }) {
  return (
    <section className="od-panel" aria-labelledby="od-request">
      <div className="od-panel-header">
        <h2 id="od-request">Customer request &amp; source evidence</h2>
      </div>
      <p className="od-section-desc">
        Customer statements and extracted values are distinct from verified operational availability.
      </p>

      {/* Primary Customer Message Evidence */}
      <div className="od-sub-section">
        <h3>Original message references</h3>
        {d.messages?.length ? (
          <div className="od-message-links">
            <ul className="od-bullet-list">
              {d.messages.map(message => (
                <li key={message.id}>
                  <a href={`#${evidenceAnchor(message.id)}`} className="od-inline-link">
                    Read original message {message.id}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="od-muted">Original message evidence not available.</p>
        )}

        {d.messages?.map(message => (
          <article
            className="od-evidence-card"
            id={evidenceAnchor(message.id)}
            key={message.id}
            tabIndex={-1}
          >
            <div className="od-evidence-header">
              <h4>Message {message.id}</h4>
              <span className="od-evidence-meta">
                {shown(message.tier)} · {shown(message.channel)} · {timestamp(message.receivedAt)}
              </span>
            </div>
            <blockquote>{shown(message.text)}</blockquote>
          </article>
        ))}
      </div>

      {/* Structured Fields & Validation */}
      <div className="od-sub-section">
        <h3>Structured fields and provenance</h3>
        <p className="od-section-desc">
          Field status is source-supplied. Absent validation remains Not verified.
        </p>
        {d.fields?.length ? (
          <div
            className="od-scroll"
            role="region"
            aria-label="Structured order fields, scroll horizontally"
            tabIndex={0}
          >
            <table className="od-table">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Captured / corrected value</th>
                  <th scope="col">Validation</th>
                  <th scope="col">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {d.fields.map((field, i) => (
                  <tr key={i}>
                    <th scope="row">{field.name}</th>
                    <td>{shown(field.value)}</td>
                    <td>
                      <span
                        className={`od-field-badge od-field-${(field.status ?? 'unverified').toLowerCase()}`}
                      >
                        {[
                          'VALID',
                          'MISSING',
                          'AMBIGUOUS',
                          'CONFLICTING',
                          'UNVERIFIED',
                        ].includes(field.status ?? '')
                          ? field.status
                          : 'Not verified'}
                      </span>
                    </td>
                    <td>
                      {field.evidence?.length ? (
                        <ul className="od-evidence-list">
                          {field.evidence.map((e, j) => (
                            <li key={j}>
                              <span className="od-evidence-ref">{e.ref}</span>
                              {e.quote && <blockquote>{e.quote}</blockquote>}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        'Not verified'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="od-muted">Structured fields not available.</p>
        )}
      </div>

      {/* Expandable Technical Details & Source Evidence */}
      <details className="od-details-expander">
        <summary>View Technical Details &amp; Conflicts</summary>
        <div className="od-expander-content">
          <h4>Source-reported conflicts</h4>
          <Values
            values={d.fieldConflicts}
            empty="No conflict data supplied; this does not prove validity."
          />
          <div className="od-legacy-action">
            <a href="#legacy-order-context" className="od-inline-link">
              Open existing P1 review, validation, versions and Core publishing
            </a>
          </div>
        </div>
      </details>
    </section>
  );
}

export function FeasibilitySummary({ detail: d, now }: { detail: OrderDetail; now: number }) {
  const state = assessmentState(d, now);
  const a = d.assessment;
  const explanations: Record<string, string> = {
    FEASIBLE:
      'Backend assessment reports feasibility only for the identified order version, snapshot and assumptions.',
    CONDITIONAL:
      'Backend assessment depends on the stated conditions; unmet conditions still require verification.',
    INFEASIBLE:
      'Backend assessment reports constraints preventing the assessed request.',
    UNKNOWN:
      'Evidence, completeness, snapshot freshness or version authority is insufficient. Reassessment or verification is required.',
  };

  return (
    <section className="od-panel od-assessment" aria-labelledby="od-feasibility">
      <div className="od-panel-header">
        <h2 id="od-feasibility">Feasibility assessment</h2>
        <StatusBadge dimension="feasibility" state={state} />
      </div>

      <p className="od-assessment-explanation">{explanations[state]}</p>

      {!a ? (
        <div className="od-empty-assessment">
          <h3>Assessment Not Available</h3>
          <p>No verified feasibility assessment has been provided yet.</p>
          <p role="status" className="od-muted">
            Pending-order assessment API unavailable. Legacy commitment assessments cannot
            substitute for this request.
          </p>
        </div>
      ) : (
        <Facts
          values={[
            ['Reported backend assessment', shown(a.status)],
            ['Assessment ID / version', `${shown(a.id)} / ${shown(a.version)}`],
            ['Assessed order version', shown(a.orderVersion)],
            ['Snapshot ID', shown(a.snapshotId)],
            ['Snapshot timestamp', timestamp(a.snapshotAt)],
            ['Snapshot age', snapshotAge(a.snapshotAt, now)],
            ['Backend freshness verdict', a.freshness ?? 'UNKNOWN'],
            [
              'Evidence verification',
              a.sourceVerified ? 'Source-reported verified' : 'Not verified',
            ],
            [
              'Assessment completeness',
              a.complete ? 'Source-reported complete' : 'Incomplete / unknown',
            ],
          ]}
        />
      )}

      <p className="od-notice">
        Assessment does not accept the order or reserve any stock, lot or capacity.
      </p>
    </section>
  );
}

export function InventoryAssessmentPanel({ detail: d }: { detail: OrderDetail }) {
  return (
    <section className="od-panel" aria-labelledby="od-inventory">
      <div className="od-panel-header">
        <h2 id="od-inventory">Inventory &amp; materials</h2>
      </div>
      <p className="od-section-desc">
        Backend quantities are shown with their own units. Incoming supply remains separate from
        stock on hand; no quantities are combined here.
      </p>

      {!d.materials?.length ? (
        <p className="od-muted">
          Material availability cannot be verified: BOM, stock, lots and effective availability are
          not supplied.
        </p>
      ) : (
        <div
          className="od-scroll"
          role="region"
          aria-label="Materials and lots, scroll horizontally"
          tabIndex={0}
        >
          <table className="od-table">
            <thead>
              <tr>
                {[
                  'Material / BOM',
                  'Required / on hand',
                  'Effective / shortage',
                  'Lot / location / expiry',
                  'Incoming supply',
                  'Freshness / constraints',
                ].map(h => (
                  <th key={h} scope="col">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.materials.map((m, i) => (
                <tr key={i}>
                  <th scope="row">
                    <strong>{m.material}</strong>
                    <small className="od-cell-sub">BOM: {shown(m.bom)}</small>
                  </th>
                  <td>
                    Required: {quantityText(m.required)}
                    <small className="od-cell-sub">Stock on hand: {quantityText(m.onHand)}</small>
                  </td>
                  <td>
                    Effective availability (backend): {quantityText(m.effective)}
                    <small className="od-cell-sub">
                      Shortage (backend): {quantityText(m.shortage)}
                    </small>
                  </td>
                  <td>
                    {shown(m.lot)}
                    <small className="od-cell-sub">Location: {shown(m.location)}</small>
                    <small className="od-cell-sub">
                      Expiry:{' '}
                      {validDate(m.expiresAt)
                        ? `${m.expiresAt} (date only; cutoff unknown)`
                        : timestamp(m.expiresAt)}
                    </small>
                    <small className="od-cell-sub">Relevance to deadline: Not verified</small>
                  </td>
                  <td>
                    {m.incoming?.length ? (
                      <ul className="od-compact-list">
                        {m.incoming.map((s, j) => (
                          <li key={j}>
                            {quantityText(s.quantity)} · {shown(s.status)}
                            <small className="od-cell-sub">Due: {timestamp(s.dueAt)}</small>
                            <Values values={s.evidence} empty="Supply evidence not available" />
                          </li>
                        ))}
                      </ul>
                    ) : (
                      'Not available'
                    )}
                  </td>
                  <td>
                    {timestamp(m.sourceAt)}
                    <Values values={m.constraints} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="od-sub-section">
        <h3>Existing reservations and separately reported demand</h3>
        <p className="od-section-desc">
          Accepted reservations require both source-reported ACCEPTED state and explicit
          reservation verification. Other rows are reported demand, not verified reservations.
        </p>
        {d.reservations?.length ? (
          <ul className="od-bullet-list">
            {d.reservations.map((r, i) => (
              <li key={i}>
                <strong>
                  {r.orderStatus === 'ACCEPTED' && r.verified === true
                    ? 'Accepted reservation'
                    : 'Reported demand — reservation not verified'}
                </strong>{' '}
                · {r.id} · <Link to={`/orders/${encodeURIComponent(r.orderId)}`}>{r.orderId}</Link>{' '}
                · {shown(r.orderStatus)}
                <small className="od-cell-sub">
                  {shown(r.resource)} · {quantityText(r.quantity)}
                </small>
                <Values values={r.evidence} empty="Reservation evidence not available" />
              </li>
            ))}
          </ul>
        ) : (
          <p className="od-muted">
            Existing reservation records not available; no free stock is inferred.
          </p>
        )}
      </div>
    </section>
  );
}

export function CapacityAssessmentPanel({ detail: d }: { detail: OrderDetail }) {
  return (
    <section className="od-panel" aria-labelledby="od-capacity">
      <div className="od-panel-header">
        <h2 id="od-capacity">Capacity &amp; schedule</h2>
      </div>

      {!d.capacities?.length ? (
        <p className="od-muted">
          Capacity, production windows, accepted workload and schedule conflicts cannot be verified.
        </p>
      ) : (
        d.capacities.map((c, i) => (
          <article className="od-evidence-card" key={i}>
            <h3>{c.resource}</h3>
            <Facts
              values={[
                ['Required workload', quantityText(c.workload)],
                ['Available capacity (backend)', quantityText(c.available)],
                ['Production window start', timestamp(c.windowStart)],
                ['Production window end', timestamp(c.windowEnd)],
                ['Capacity gap', 'Unavailable — no source gap supplied'],
                ['Capacity source updated', timestamp(c.sourceAt)],
              ]}
            />
            <h4>Schedule / deadline conflicts</h4>
            <Values values={c.conflicts} />
            <h4>Bottlenecks</h4>
            <Values values={c.bottlenecks} />
            <h4>Time assumptions</h4>
            <Values values={c.assumptions} />
          </article>
        ))
      )}

      <p className="od-section-desc">
        No frontend scheduler or free-capacity calculation is performed.
      </p>
    </section>
  );
}

export function PricingProvenancePanel({ detail: d }: { detail: OrderDetail }) {
  const p = d.pricing;
  if (!p || p.access !== 'AUTHORIZED') {
    return (
      <section className="od-panel" aria-labelledby="od-price">
        <div className="od-panel-header">
          <h2 id="od-price">Pricing, costs &amp; expected profit</h2>
        </div>
        <p className="od-muted">
          {p?.access === 'REDACTED'
            ? 'Financial data redacted by source authorization.'
            : 'Financial authorization or source data not available. Expected profit unknown.'}
        </p>
      </section>
    );
  }

  return (
    <section className="od-panel" aria-labelledby="od-price">
      <div className="od-panel-header">
        <h2 id="od-price">Pricing, costs &amp; expected profit</h2>
      </div>

      <Facts
        values={[
          ['Customer-offered price (claim)', moneyText(p.customerPrice, p.currency)],
          [
            'Authorized quote (source-reported)',
            p.sourceVerified ? moneyText(p.quotedPrice, p.currency) : 'Not verified',
          ],
          ['Approved price source', shown(p.priceSource)],
          ['Quote / price version', shown(p.quoteVersion)],
          ['Price disclosed', shown(p.disclosed)],
          ['Price agreed', shown(p.agreed)],
          ['Financial source updated', timestamp(p.sourceAt)],
          ['Cost provenance', shown(p.costSource)],
          [
            'Expected profit',
            p.sourceVerified && !p.missingCosts?.length
              ? profitText({
                  amount: p.profit,
                  currency: p.currency,
                  costComplete: p.costComplete,
                  priceSource: p.priceSource,
                  costSource: p.costSource,
                })
              : 'Not verified / cost incomplete — expected profit unavailable',
          ],
        ]}
      />

      <div className="od-sub-section">
        <h3>Cost components (no frontend totals)</h3>
        {p.costs?.length ? (
          <ul className="od-bullet-list">
            {p.costs.map((c, i) => (
              <li key={i}>
                {c.component}: {moneyText(c.amount, p.currency)} · {shown(c.source)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="od-muted">
            BOM/material, inventory valuation, labour and delivery cost coverage not available.
          </p>
        )}
      </div>

      <div className="od-sub-section">
        <h3>Missing cost components</h3>
        <Values
          values={p.missingCosts}
          empty={p.costComplete ? 'Source reports complete coverage.' : 'Coverage unknown / incomplete.'}
        />
      </div>
    </section>
  );
}

export function DecisionReadinessPanel({ detail: d, now }: { detail: OrderDetail; now: number }) {
  const a = d.assessment;
  return (
    <section className="od-panel" aria-labelledby="od-decision">
      <div className="od-panel-header">
        <h2 id="od-decision">Recommendation &amp; decision readiness · read only</h2>
      </div>
      <p className="od-section-desc">Backend recommendation: {shown(a?.recommendation)}</p>

      {assessmentState(d, now) === 'UNKNOWN' && (
        <p className="od-notice">
          Assessment is not current and verified for this order version. Do not treat this
          recommendation as approval.
        </p>
      )}

      {(
        [
          ['Reasons', a?.reasons],
          ['Hard constraints', a?.constraints],
          ['Soft preferences', a?.preferences],
          ['Blocking factors', a?.blockers],
          ['Outstanding conditions', a?.conditions],
          ['Assumptions', a?.assumptions],
          ['Assessment evidence references', a?.evidence],
          ['Missing evidence', a?.missingEvidence],
        ] as [string, string[] | undefined][]
      ).map(([label, values]) => (
        <div key={label} className="od-sub-section">
          <h3>{label}</h3>
          <Values values={values} />
        </div>
      ))}

      <p className="od-notice">
        Decision commands remain unavailable until verified backend integration. The Order Decision
        workspace below separates exact terms, proposals, amendments and recorded outcomes;
        frontend assessment does not grant execution authority.
      </p>

      {d.commitmentId && (
        <p className="od-commitment-link">
          Explicit related commitment:{' '}
          <Link to={`/commitments/${encodeURIComponent(d.commitmentId)}`}>{d.commitmentId}</Link>{' '}
          (existing commitment workflow; not a pending-order assessment).
        </p>
      )}
    </section>
  );
}
