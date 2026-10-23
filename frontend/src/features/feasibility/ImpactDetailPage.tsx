import { Link, useParams } from "react-router-dom";
import type { CommitmentImpactView, ImpactClassification, ImpactView, P2DataSource } from "./models";
import { hasEvidenceReferences, validateImpact } from "./data";
import { Evidence, LoadFailure, SourceNotice, useFeatureLoad } from "./presentation";
import "./feasibility.css";

const load = async (source: P2DataSource, id: string) => validateImpact(await source.loadImpact(id), id, source.tenantId);
const groups: [ImpactClassification, string][] = [
  ["CONFIRMED_IMPACT", "Confirmed impacted commitments"],
  ["VERIFIED_UNAFFECTED", "Verified unaffected commitments"],
  ["UNKNOWN", "UNKNOWN impact attribution"],
  ["PRE_EXISTING_UNCHANGED", "Pre-existing unchanged constraints"],
  ["NO_NEW_ADVERSE_DELTA", "No new adverse delta (not verified unaffected)"],
];
export function ImpactDetailPage({ source }: { source?: P2DataSource }) {
  const { id = "" } = useParams();
  const state = useFeatureLoad(source, id, load);
  return <div className="p2-feature"><SourceNotice source={source} />
    {state.loading ? <p role="status">Loading operational impact…</p> : state.error ? <LoadFailure error={state.error} retry={state.retry} /> :
      state.data ? <ImpactContent view={state.data} /> : <p>No impact assessment available.</p>}
  </div>;
}
function ImpactContent({ view }: { view: ImpactView }) {
  const missing = view.candidate_commitment_ids.filter((id) => !view.impacts.some((r) => r.commitment_id === id));
  return <>
    <header className="page-heading"><div><p className="eyebrow">P2 · {view.impact_id}</p><h2>Operational impact detail</h2>
      <p className="muted">Dependency edges discover candidates. Recalculation and causal evidence establish impact.</p></div></header>
    <nav className="workflow-links" aria-label="Related workflow pages">
      <Link to="/activity">Activity</Link>
      {view.candidate_commitment_ids.map(id => <Link key={id} to={`/commitments/${encodeURIComponent(id)}`}>Commitment {id}</Link>)}
    </nav>
    <section className="notice-card" aria-label="Trigger and snapshots"><h3>Trigger and changed resources</h3>
      <p>{view.event_type} · {view.event_id}</p><p>Snapshots {view.before_snapshot_version} → {view.after_snapshot_version}</p>
      <Evidence refs={view.trigger_evidence_refs} />
      {!view.discovery_complete && <p className="p2-warning">Dependency discovery incomplete; undiscovered impact remains UNKNOWN.</p>}
      {view.changes.length ? <div className="p2-scroll" tabIndex={0} role="region" aria-label="Scrollable resource changes"><table><caption>Changed resources</caption>
        <thead><tr>{["Resource", "Before", "After", "Source evidence"].map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{view.changes.map((r) => <tr key={`${r.kind}:${r.resource_id}`}><th scope="row">{r.kind} · {r.resource_id}</th><td>{r.before}</td><td>{r.after}</td><td><Evidence refs={r.evidence_refs} /></td></tr>)}</tbody>
      </table></div> : <p>Before/after resource values unavailable; OperationalChange and source-row enrichment are required.</p>}
      <h4>Candidate commitments</h4><p>{view.candidate_commitment_ids.join(", ") || "No candidates supplied"}</p>
      <p>An empty affected set does not establish that all candidates were verified unaffected.</p>
      <p>Core risk change: unavailable unless an approved Core transition with evidence is supplied. Local event intents do not update risk.</p>
    </section>
    {groups.map(([classification, label]) => {
      const rows = view.impacts.filter((r) => r.classification === classification);
      return <section key={classification} className="notice-card" aria-label={label}><h3>{label}</h3>
        {rows.map((row) => <ImpactCard key={row.commitment_id} row={row} />)}
        {classification === "UNKNOWN" && missing.map((id) => <article key={id}><h4>{id}</h4><p>UNKNOWN — candidate has no recalculation/evidence result.</p></article>)}
        {!rows.length && !(classification === "UNKNOWN" && missing.length) && <p>{classification === "VERIFIED_UNAFFECTED" ? "None verified" : "None established"}</p>}
      </section>;
    })}
    <section className="notice-card" aria-label="Dependencies"><h3>Dependency paths</h3>
      <div className="p2-scroll" tabIndex={0} role="region" aria-label="Scrollable dependencies"><table><caption>Dependency evidence</caption><thead><tr><th scope="col">Commitment</th><th scope="col">Resource path</th><th scope="col">Relationships</th><th scope="col">Evidence</th></tr></thead>
        <tbody>{view.impacts.flatMap((row) => row.dependency_paths.map((path, i) => <tr key={`${row.commitment_id}:${i}`}><th scope="row">{row.commitment_id}</th><td>{path.nodes.map((n) => `${n.kind}: ${n.resource_id}`).join(" → ")}</td><td>{path.relationships.join(" → ")}</td><td><Evidence refs={path.evidence_refs} /></td></tr>))}</tbody>
      </table></div>
      {!view.impacts.some((r) => r.dependency_paths.length) && <p>Dependency paths unavailable.</p>}
      <p>Provenance: P2 ImpactAssessment classifications/deltas/buffers/paths; trigger and source rows require an approved P5 public adapter. No risk transition is inferred.</p>
    </section>
  </>;
}
function ImpactCard({ row }: { row: CommitmentImpactView }) {
  return <article className="p2-impact-card"><h4>{row.commitment_id}</h4><p>{row.classification}</p>
    <ul>{row.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
    {[...row.material_deltas, ...row.hard_constraint_deltas].map((delta, i) => <div key={`${delta.resource_id}:${i}`}>
      <p>{delta.code ?? "MATERIAL_SHORTAGE"} · {delta.resource_id}: {delta.before_shortage ?? "UNKNOWN"} → {delta.after_shortage ?? "UNKNOWN"} {delta.unit ?? ""} · {delta.severity_change ?? "Severity unavailable"}</p>
      <p>Constraint deadline: {delta.deadline ?? "unavailable"}</p><Evidence refs={delta.evidence_refs} />
    </div>)}
    {row.buffers.map((b) => {
      const supported = hasEvidenceReferences(b.evidence_refs);
      return <div key={`${b.resource_id}:${b.unit}`}><p>{supported ? "Verified buffer" : "Reported buffer — evidence unavailable"}: {b.resource_id} · {b.value} {b.unit}</p><Evidence refs={supported ? b.evidence_refs : []} /></div>;
    })}
    {row.risk_change?.evidence_refs.length ? <div><p>Core risk: {row.risk_change.before} → {row.risk_change.after}</p><Evidence refs={row.risk_change.evidence_refs} /></div> : null}
    <Evidence refs={row.evidence_refs} />
  </article>;
}
