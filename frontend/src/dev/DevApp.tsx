import { Inbox } from '../features/context/Inbox';
import { DurableInbox } from '../features/context/DurableInbox';
import './dev.css';

export function DevApp() {
  const preview = window.location.pathname === '/inbox/fixtures';
  return <><header className="p1-dev-shell"><a href="/inbox">MonManTAI<span> / Business Context</span></a><nav aria-label="P1 development views"><a href="/inbox" aria-current={!preview ? 'page' : undefined}>Inbox</a><a href="/inbox/fixtures" aria-current={preview ? 'page' : undefined}>Fixture preview</a></nav><span>Synthetic development entry point · P5 shell pending</span></header><main>{preview ? <Inbox /> : <DurableInbox />}</main></>;
}
