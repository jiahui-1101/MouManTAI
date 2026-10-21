import { Inbox } from '../features/context/Inbox';
import './dev.css';

export function DevApp() {
  return <><header className="p1-dev-shell"><a href="/inbox">MonManTAI<span> / Business Context</span></a><span>Synthetic development entry point · P5 shell pending</span></header><main><Inbox /></main></>;
}
