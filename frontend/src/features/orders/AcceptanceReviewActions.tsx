import { useState } from 'react';
import { Button, ConfirmationDialog } from '../../shared/ui';
import type { OrderDetail } from './detailTypes';
import type { OrderDecisionSnapshot } from './decisionTypes';
import { DecisionTermsView } from './DecisionTermsView';
import { commandDependency } from './decisionGuards';
import { shown } from './queue';

/** Read-only review, never a command confirmation or an execution gate. */
export function AcceptanceReviewActions({ order, snapshot }: { order: OrderDetail; snapshot: OrderDecisionSnapshot }) {
  const [open, setOpen] = useState(false);
  return <div className="decision-review-actions">
    <p>Order {order.id} · Request version {shown(snapshot.requestVersion)}. Review exact terms before any future authorized command.</p>
    <div className="decision-action-buttons"><Button variant="secondary" disabled={!snapshot.exactOriginal} onClick={() => setOpen(true)}>Review exact acceptance terms</Button>
      <Button disabled aria-describedby="acceptance-command-dependency">Accept as Requested</Button><Button disabled aria-describedby="acceptance-command-dependency">Accept Agreed Proposal</Button></div>
    <p id="acceptance-command-dependency">{commandDependency} No acceptance, duplicate submission or optimistic status update can be triggered here.</p>
    <ConfirmationDialog open={open} onOpenChange={setOpen} title="Read-only acceptance terms review"
      description="This is an inspection of source-supplied terms, not approval or submission. Closing this review does not accept an order, establish customer assent or reserve resources."
      confirmLabel="Close review" onConfirm={() => setOpen(false)} scope={<>
      <p>Order ID: {order.id} · Source request version: {shown(snapshot.requestVersion)}</p>
      <DecisionTermsView terms={snapshot.exactOriginal} title="Terms supplied for inspection" financial={snapshot.financialAccess === 'AUTHORIZED'} />
      <p>{commandDependency}</p>
    </>} />
  </div>;
}
