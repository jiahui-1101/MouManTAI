import { ContentCard } from '../../shared/ui';
import type { OrderDetail } from './detailTypes';
import type { OrderDecisionSnapshot } from './decisionTypes';
import { receiptLabel } from './decisionGuards';
import { timestamp } from './queue';

/** Independent source projections. Never derive agreement/reservation/fulfilment from lifecycle. */
export function OrderProgressPanel({ order, snapshot }: { order?: OrderDetail; snapshot?: OrderDecisionSnapshot }) {
  const bound = !!order && !!snapshot && order.id === snapshot.orderId && order.tenantId === snapshot.tenantId;
  const verifiedReservations = bound ? snapshot.receipts?.filter(receipt => receiptLabel(receipt, snapshot).startsWith('Source records acceptance')) ?? [] : [];
  const report = snapshot?.legacyFulfilment;
  const fulfilment = bound && report && order.commitmentId === report.commitmentId &&
    (!snapshot.currentAgreement || snapshot.currentAgreement.version === report.commitmentVersion) ? report : undefined;
  return <ContentCard title="Order progress · independent source states" className="decision-progress">
    <p>Accepted ≠ customer agreed ≠ reserved ≠ fulfilled. Synthetic records are demonstrations, not trusted execution or delivery evidence.</p>
    <dl>
      <div><dt>Order Acceptance</dt><dd>{bound && order.status?.trim() ? `Source order lifecycle: ${order.status}` : 'Unavailable — no authoritative order acceptance state'}</dd></div>
      <div><dt>Customer Agreement</dt><dd>{bound && snapshot.currentAgreement ? `Source agreement record · version ${snapshot.currentAgreement.version} · ${snapshot.currentAgreement.terms.basis}` : 'Unavailable — no current agreement record'}<small>A displayed agreement record does not independently prove exact customer assent. Review its terms, proposal identity and evidence.</small></dd></div>
      <div><dt>Resource Reservation</dt><dd>{verifiedReservations.length ? <ul>{verifiedReservations.map(receipt => <li key={receipt.id}>Source-reported confirmed reservation {receipt.reservationRef} · Receipt {receipt.id} · Audit {receipt.auditRef}</li>)}</ul> : 'Unavailable — no matching verified reservation receipt'}</dd></div>
      <div><dt>Fulfilment</dt><dd>{fulfilment ? <>Core source state: {fulfilment.state} · Commitment version {fulfilment.commitmentVersion}<small>Source updated: {timestamp(fulfilment.sourceAt)} · Evidence: {fulfilment.evidence.join(', ') || 'Unavailable'}. This source report is not independent proof of real delivery.</small></> : 'Unavailable — no current fulfilment projection supplied'}<small>Delivery method, acceptance, agreement, reservations and historical audit text cannot substitute for a verified fulfilment state.</small></dd></div>
    </dl>
    <p>Source: {bound ? snapshot.sourceLabel : 'Unavailable / source identity not verified'}</p>
  </ContentCard>;
}
