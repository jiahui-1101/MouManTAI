import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { FeasibilityView, P2DataSource } from "./models";
import { assessmentCaution, errorText, validateFeasibility, validateRecalculation } from "./data";
import { Evidence, LoadFailure, SourceNotice, useFeatureLoad } from "./presentation";
import "./feasibility.css";

const load = async (source: P2DataSource, id: string) => validateFeasibility(await source.loadFeasibility(id), id, source.tenantId);

export function CommitmentFeasibilityPage({ source }: { source?: P2DataSource }) {
  const { id = "" } = useParams();
  const state = useFeatureLoad(source, id, load);
  return <div className="p2-feature"><SourceNotice source={source} />
    {state.loading ? <p role="status">Loading commitment feasibility…</p> : state.error ? <LoadFailure error={state.error} retry={state.retry} /> :
      state.data ? <FeasibilityContent key={`${source?.tenantId}:${id}`} initial={state.data} source={source} reload={state.retry} /> : <p>No commitment available.</p>}
  </div>;
}

function FeasibilityContent({ initial, source, reload }: { initial: FeasibilityView; source?: P2DataSource; reload: () => void }) {
  const [view, setView] = useState(initial);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const [received, setReceived] = useState(false);
  const [displayTime, setDisplayTime] = useState(Date.now);
  const epoch = useRef(0);
  const submitting = useRef(false);
  useEffect(() => {
    const timer = window.setInterval(() => setDisplayTime(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  useLayoutEffect(() => {
    epoch.current += 1;
    setView(initial); setError(undefined); setPending(false); setReceived(false); submitting.current = false;
    return () => { epoch.current += 1; };
  }, [initial, source]);
  async function recalculate() {
    if (submitting.current || source?.mode !== "public-api" || !source.recalculate || view.current_snapshot_version === null) return;
    const generation = epoch.current;
    submitting.current = true; setPending(true); setError(undefined); setReceived(false);
    try {
      const next = await source.recalculate(view.commitment.commitment_id, {
        expected_commitment_version: view.commitment.commitment_version, expected_snapshot_version: view.current_snapshot_version,
      });
      if (generation !== epoch.current) return;
      setView(validateRecalculation(next, view, source.tenantId)); setDisplayTime(Date.now()); setReceived(true);
    } catch (failure) { if (generation === epoch.current) setError(failure); }
    finally { if (generation === epoch.current) { submitting.current = false; setPending(false); } }
  }
  const c = view.commitment, a = view.assessment, d = view.details;
  // Preview is explicitly a historical illustration; live results expire at display time.
  const caution = assessmentCaution(view, source?.mode === "synthetic-preview" && a ? Date.parse(a.assessed_at) : displayTime);
  const status = !a ? "NOT_ASSESSED" : a.status === "NOT_ASSESSED" ? "NOT_ASSESSED" : caution ? "UNKNOWN" : a.status;
  const canRecalculate = source?.mode === "public-api" && Boolean(source.recalculate) && view.current_snapshot_version !== null;
  return <>
    <header className="page-heading"><div><p className="eyebrow">P2 · Commitment {c.commitment_id}</p><h2>Commitment feasibility detail</h2>
      <p className="muted">Calculated against a versioned snapshot. FEASIBLE does not guarantee future delivery.</p></div>
      <div><button disabled={!canRecalculate || pending} onClick={recalculate}>{pending ? "Recalculating…" : "Recalculate"}</button></div>
    </header>
    <nav className="workflow-links" aria-label="Related workflow pages">
      <Link to={`/orders/${encodeURIComponent(c.order_id)}`}>Order context</Link>
      <Link to={`/recovery/${encodeURIComponent(c.commitment_id)}`}>Recovery case</Link>
      <Link to="/activity">Activity</Link>
    </nav>
    {!canRecalculate && <p className="p2-warning">Recalculate unavailable: P5 persistence and authorization adapter and authoritative snapshot version are required.</p>}
    {pending && <p role="status">Previous assessment retained while a new assessment is requested.</p>}
    {error !== undefined && <div><p role="alert">{errorText(error)}</p><button onClick={recalculate} disabled={pending}>Retry recalculation</button> <button onClick={reload}>Reload current data</button></div>}
    {received && <p role="status">Assessment received. Review its status and evidence below.</p>}
    <section className="notice-card" aria-label="Core commitment">
      <h3>Core commitment · version {c.commitment_version}</h3><dl className="p2-facts">
        <div><dt>Commitment ID</dt><dd>{c.commitment_id}</dd></div><div><dt>Order ID</dt><dd>{c.order_id}</dd></div><div><dt>Customer ID</dt><dd>{c.customer_id}</dd></div>
        <div><dt>Agreement</dt><dd>{c.agreement_state}</dd></div><div><dt>Risk</dt><dd>{c.risk_state}</dd></div>
        <div><dt>{c.agreement_state === "CONFIRMED" ? "Confirmed terms" : "Recorded terms (not confirmed)"}</dt><dd>{c.terms.quantity} {c.terms.unit} · {c.terms.sku}</dd></div>
        <div><dt>Customer deadline</dt><dd><time dateTime={c.terms.deadline ?? undefined}>{c.terms.deadline ?? "Not provided"}</time></dd></div>
        <div><dt>Special instructions</dt><dd>{c.terms.special_instructions ?? "None recorded"}</dd></div>
      </dl><p>Core evidence</p><Evidence refs={c.evidence_refs} />
    </section>
    <section className="notice-card" aria-label="Assessment summary"><h3>Assessment summary</h3>
      <strong data-testid="feasibility-status" className="p2-status">{status}</strong>
      {caution && <p className="p2-warning">{caution}</p>}
      {a && <><p>Recorded assessment: {a.status}</p><p>Assessment ID: <code>{a.assessment_id}</code></p>
        <p>Snapshot {a.snapshot_version}</p><p>Assessed at <time dateTime={a.assessed_at}>{a.assessed_at}</time></p>
        <p>Commitment version {a.commitment_version} · Solver {a.solver_status}</p></>}
      <p>Current snapshot version: {view.current_snapshot_version ?? "unavailable"}</p>
      <p>Evidence completeness: {d ? d.evidence_complete ? "complete for supplied snapshot" : "incomplete" : "unavailable"}</p>
    </section>
    <section className="notice-card" aria-label="Material requirements"><h3>Materials</h3>
      <p className="muted">Usable, reserved and confirmed incoming amounts are allocations to this demand at need time. They are not total warehouse stock. Reserved means allocated owned reservation; amounts are counted separately.</p>
      {d?.materials.length ? <div className="p2-scroll" tabIndex={0} role="region" aria-label="Scrollable materials"><table>
        <caption>Material allocation at need time</caption><thead><tr>{["Material / line", "Required", "Usable", "Reserved", "Confirmed incoming", "Shortage", "Need time", "Evidence"].map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{d.materials.map((r) => <tr key={`${r.line_id}:${r.sku_id}`}><th scope="row">{r.sku_id}<small>{r.line_id}</small></th>
          {[r.required, r.usable, r.reserved, r.confirmed_incoming, r.shortage].map((n, i) => <td key={i}>{n} {r.unit}</td>)}<td>{r.needed_by}</td><td><Evidence refs={r.evidence_refs} /></td></tr>)}</tbody>
      </table></div> : <p>Detailed material fields unavailable. Shared FeasibilityAssessment does not expose the required allocation rows; no zero stock is assumed.</p>}
    </section>
    <section className="notice-card" aria-label="Production capacity"><h3>Production and deadline constraints</h3>
      <p className="muted">Supplied fixed bookings only. Available minutes are deadline-bounded diagnostics; an invalid booking does not prove every reschedule impossible.</p>
      {d?.operations.length ? <div className="p2-scroll" tabIndex={0} role="region" aria-label="Scrollable production"><table><caption>Fixed production bookings</caption>
        <thead><tr>{["Line / resources", "Start", "Finish", "Required minutes", "Available minutes", "Evidence"].map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{d.operations.map((r) => <tr key={r.line_id}><th scope="row">{r.line_id}<small>{r.resource_ids.join(", ")}</small></th><td>{r.start_at}</td><td>{r.finish_at}</td><td>{r.required_minutes}</td><td>{r.available_minutes ?? "UNKNOWN"}</td><td><Evidence refs={r.evidence_refs} /></td></tr>)}</tbody>
      </table></div> : <p>Production detail unavailable. Processing time, free capacity and conflicts require a public P5 detail adapter.</p>}
      <h4>Constraint reasons</h4>{a?.constraints.length ? <ul>{a.constraints.map((r, i) => <li key={`${r.code}:${r.resource_id}:${i}`}>
        <strong>{r.code}</strong> · {r.resource_id} · {r.severity}{r.shortage != null && ` · ${r.shortage} ${r.unit ?? ""}`}
        {r.deadline && <p>Constraint deadline: {r.deadline}</p>}<Evidence refs={r.evidence_refs} />
      </li>)}</ul> : <p>No constraint reasons supplied. This alone does not establish feasibility.</p>}
    </section>
    <section className="notice-card" aria-label="Source freshness"><h3>Source freshness</h3>
      {d?.sources.length ? <ul>{d.sources.map((s) => <li key={s.source_id}><strong>{s.source_id} · {s.status}</strong><p>{s.source_ref}</p><p>Observed {s.observed_at ?? "UNKNOWN"} · valid through {s.valid_through ?? "UNKNOWN"}</p><Evidence refs={s.evidence_refs} /></li>)}</ul> : <p>Source freshness unavailable. A timestamp alone does not establish trusted current evidence.</p>}
    </section>
    <section className="notice-card" aria-label="Evidence and assumptions"><h3>Evidence and assumptions</h3><Evidence refs={a?.evidence_refs ?? []} />
      {a?.assumptions.length ? <ul>{a.assumptions.map((text) => <li key={text}>{text}</li>)}</ul> : <p>Assumptions unavailable or none supplied.</p>}
      <p>Provenance: Core identity/terms/state; shared assessment metadata; P2 material and production projections when supplied. Missing fields require P5 public response enrichment. Evidence references are identifiers, not verified document content.</p>
    </section>
  </>;
}
