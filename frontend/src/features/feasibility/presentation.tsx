import { useEffect, useState } from "react";
import type { P2DataSource } from "./models";
import { errorText, requireSource } from "./data";

export function Evidence({ refs }: { refs: string[] }) {
  return refs.length ? <ul className="p2-evidence">{refs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul> : <p>Evidence unavailable.</p>;
}
export function SourceNotice({ source }: { source?: P2DataSource }) {
  return source?.mode === "synthetic-preview" ? <p role="note" className="notice-card p2-warning">
    Synthetic preview — illustrative data, not persisted. These results do not establish current operational state.
  </p> : null;
}
export function LoadFailure({ error, retry }: { error: unknown; retry: () => void }) {
  return <div className="notice-card p2-load-failure" role="alert">
    <p className="eyebrow">Data unavailable</p><h2>Could not load this operational view</h2>
    <p>{errorText(error)}</p><p className="muted">No feasibility or impact result is shown until the source responds.</p>
    <button onClick={retry}>Retry loading</button>
  </div>;
}
// Local page lifecycle only. P5 owns shared caching/auth/query setup.
export function useFeatureLoad<T>(source: P2DataSource | undefined, id: string, loader: (source: P2DataSource, id: string) => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ source?: P2DataSource; id: string; data?: T; error?: unknown; loading: boolean }>({ id, loading: true });
  useEffect(() => {
    let active = true;
    setState({ source, id, loading: true });
    Promise.resolve().then(() => loader(requireSource(source), id)).then(
      (data) => { if (active) setState({ source, id, data, loading: false }); },
      (error: unknown) => { if (active) setState({ source, id, error, loading: false }); },
    );
    return () => { active = false; };
  }, [source, id, attempt, loader]);
  // Never flash previous tenant/route data before effect cleanup.
  const current = state.source === source && state.id === id;
  return { data: current ? state.data : undefined, error: current ? state.error : undefined,
    loading: !current || state.loading, retry: () => setAttempt((n) => n + 1) };
}
