import { ContentCard } from '../../shared/ui';
import type { OrderQueueSnapshot, StatusView } from './types';
import { OrderQueueIcon } from './OrderQueueIcon';

/** Counts are independent of filters and refer only to a source-confirmed complete snapshot.
 * Missing lifecycle values invalidate lifecycle counts; free-text risk is not a risk enum.
 */
export function OrderQueueSummary({ data, status, onStatus }: {
  data?: OrderQueueSnapshot; status: StatusView; onStatus: (status: StatusView) => void;
}) {
  const complete = data?.coverage === 'complete';
  const lifecycleKnown = complete && data.items.every(order => ['PENDING_ACCEPTANCE', 'ACCEPTED', 'REJECTED'].includes(order.status ?? ''));
  const count = (value: string) => lifecycleKnown ? data!.items.filter(order => order.status === value).length : null;
  const cards = [
    { id: 'total', label: 'Total Orders', value: complete ? data.items.length : null, icon: 'orders', tone: 'primary', filter: 'ALL',
      detail: complete ? 'Source-confirmed complete snapshot' : data ? `${data.items.length} loaded · tenant total unavailable` : 'Awaiting an authorized order snapshot' },
    { id: 'pending', label: 'Pending Acceptance', value: count('PENDING_ACCEPTANCE'), icon: 'pending', tone: 'warning', filter: 'PENDING_ACCEPTANCE', detail: 'Requests only · no reservation implied' },
    { id: 'accepted', label: 'Accepted', value: count('ACCEPTED'), icon: 'accepted', tone: 'success', filter: 'ACCEPTED', detail: 'Explicit order lifecycle status only' },
    { id: 'rejected', label: 'Rejected', value: count('REJECTED'), icon: 'rejected', tone: 'danger', filter: 'REJECTED', detail: 'Explicit order lifecycle status only' },
    { id: 'risk', label: 'High Risk', value: null, icon: 'risk', tone: 'warning', detail: 'Standardized risk-level contract unavailable' },
    { id: 'missing', label: 'Missing Information', value: null, icon: 'information', tone: 'muted', detail: 'Order completeness contract unavailable' },
  ] as const;
  return <section className="oq-summary" aria-label="Order summary">
    {cards.map(card => {
      const usable = 'filter' in card && card.value !== null;
      const body = <>
        <span className="oq-kpi-top"><span>{card.label}</span><span className={`oq-kpi-icon oq-tone-${card.tone}`}><OrderQueueIcon name={card.icon} /></span></span>
        <strong className="oq-kpi-value" data-testid={`oq-kpi-${card.id}`}>{card.value ?? '—'}</strong>
        <span className="oq-kpi-state">{card.value === null ? 'Unavailable' : 'Complete snapshot'}</span>
        <span className="oq-kpi-detail">{card.detail}</span>
      </>;
      return <ContentCard key={card.id} className={`oq-kpi ${usable && status === card.filter ? 'is-selected' : ''}`} aria-label={card.label}>
        {usable ? <button type="button" className="oq-kpi-button" aria-label={`Filter ${card.label}`} aria-pressed={status === card.filter} onClick={() => onStatus(card.filter)}>{body}</button> : <div className="oq-kpi-static">{body}</div>}
      </ContentCard>;
    })}
  </section>;
}
