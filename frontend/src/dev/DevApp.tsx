import { DurableInbox } from '../features/context/DurableInbox';
import './dev.css';

export function DevApp() {
  return (
    <>
      <header className="p1-dev-shell">
        <a href="/inbox">MonManTAI<span> / Business Context</span></a>
        <nav aria-label="P1 development views">
          <a href="/inbox" aria-current="page">Inbox</a>
        </nav>
        <span>Synthetic development entry point · P5 shell pending</span>
      </header>
      <main>
        <DurableInbox />
      </main>
    </>
  );
}
