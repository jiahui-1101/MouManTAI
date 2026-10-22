import { useState } from "react";

import { syntheticSupplierDelayScenario } from "./demoScenario";
import "./recovery.css";

function formatScenarioDate(value: string): string {
  return new Date(value).toLocaleString("en-SG", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Singapore",
  });
}

export function SyntheticRecoveryDemo() {
  const [discussionOptionId, setDiscussionOptionId] = useState<string | null>(null);
  const scenario = syntheticSupplierDelayScenario;
  const discussionOption = scenario.options.find((option) => option.id === discussionOptionId);

  return (
    <main className="recovery-page recovery-demo" data-testid="recovery-demo">
      <header className="page-heading">
        <div>
          <p className="eyebrow">P3 · Independent recovery walkthrough</p>
          <h1>Supplier delay · compare two responses</h1>
          <p className="muted">
            A fixed scenario for discussion. No live case, assessment, approval, customer response, or execution is loaded.
          </p>
        </div>
        <span className="recovery-demo-label">{scenario.label}</span>
      </header>

      <section className="recovery-demo-notice" role="note">
        <strong>Synthetic data only.</strong>
        <span>
          This walkthrough is not a P2 assessment and does not establish authoritative assessment provenance. Evidence IDs are sample references.
        </span>
      </section>

      <section className="recovery-incident-grid" aria-label="Synthetic recovery case context">
        <article className="recovery-panel">
          <div className="section-header">
            <div><p className="eyebrow">What changed</p><h2>Supplier ETA moved past the material cutoff</h2></div>
            <span className="recovery-status-pill status-infeasible">SYNTHETIC RISK SCENARIO</span>
          </div>
          <dl className="recovery-facts">
            <div><dt>Commitment</dt><dd>{scenario.commitmentId} · order {scenario.orderId}</dd></div>
            <div><dt>Customer promise</dt><dd>{scenario.quantity} {scenario.unit} {scenario.item} by {formatScenarioDate(scenario.originalDeadline)}</dd></div>
            <div><dt>Packaging</dt><dd>{scenario.usableOnHand} available for {scenario.neededQuantity} required · {scenario.inboundQuantity} inbound</dd></div>
            <div><dt>Original ETA</dt><dd>{formatScenarioDate(scenario.originalSupplierEta)}</dd></div>
            <div><dt>Revised ETA</dt><dd>{formatScenarioDate(scenario.revisedSupplierEta)}</dd></div>
            <div><dt>Material needed</dt><dd>{formatScenarioDate(scenario.requiredBy)}</dd></div>
            <div><dt>Trigger reference</dt><dd>{scenario.supplierEventId} · event time not supplied</dd></div>
            <div><dt>Potentially affected</dt><dd>{scenario.affectedCommitmentIds.join(", ")}</dd></div>
            <div><dt>Sample evidence</dt><dd><EvidenceRefs refs={scenario.evidenceRefs} /></dd></div>
          </dl>
        </article>

        <article className="recovery-panel">
          <div className="section-header"><div><p className="eyebrow">Decision boundary</p><h2>Facts and open questions</h2></div></div>
          <ul className="recovery-demo-list">
            <li><strong>Scenario input:</strong> 20 packaging units are late relative to the stated material cutoff.</li>
            <li><strong>Not established:</strong> whether an alternative supplier has stock or can meet the cutoff.</li>
            <li><strong>Not established:</strong> whether the later plan is feasible across affected commitments.</li>
            <li><strong>Customer terms:</strong> the confirmed date remains unchanged unless the customer explicitly accepts a versioned proposal.</li>
          </ul>
          <p className="recovery-demo-footnote">
            The sample does not provide a current P2 evaluation, owner preference weights, or an event timestamp. No policy recommendation is calculated.
          </p>
        </article>
      </section>

      <section className="recovery-panel" aria-labelledby="recovery-demo-options-title">
        <div className="section-header">
          <div><p className="eyebrow">Side-by-side trade-offs</p><h2 id="recovery-demo-options-title">Two distinct strategies</h2></div>
          <span className="recovery-status-pill">NO RECOMMENDATION</span>
        </div>
        <div className="recovery-options-grid">
          {scenario.options.map((option) => (
            <article className={`recovery-option-card ${discussionOptionId === option.id ? "selected" : ""}`} key={option.id}>
              <div className="recovery-option-header">
                <div><p className="recovery-option-kicker">{option.strategy.replaceAll("_", " ")}</p><h3>{option.name}</h3></div>
                <span className={`recovery-status-pill ${option.status === "CONDITIONAL" ? "status-conditional" : "status-unknown"}`}>{option.status}</span>
              </div>
              <div className="recovery-metric-grid">
                <div><span>Extra cost</span><strong>{option.cost}</strong></div>
                <div><span>Expected delay</span><strong>{option.delay}</strong></div>
                <div className="recovery-demo-impact"><span>Customer impact</span><strong>{option.customerImpact}</strong></div>
              </div>
              <div className="recovery-detail-grid recovery-demo-detail-grid">
                <div><h3>Assumptions</h3><ul>{option.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></div>
                <div><h3>Validation limitations</h3><ul>{option.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
              </div>
              <button
                type="button"
                className="btn btn-outline btn-sm"
                aria-pressed={discussionOptionId === option.id}
                onClick={() => setDiscussionOptionId(option.id)}
              >
                {discussionOptionId === option.id ? "Discussion focus selected" : "Discuss this trade-off"}
              </button>
            </article>
          ))}
        </div>
      </section>

      {discussionOption && (
        <section className="recovery-detail-card" aria-live="polite" data-testid="recovery-demo-decision-prompt">
          <p className="eyebrow">Expected manager discussion · {discussionOption.name}</p>
          <h2>Decision to consider</h2>
          <p>{discussionOption.decisionPrompt}</p>
          <div className="recovery-demo-notice">
            <strong>Discussion only.</strong>
            <span>This selection records no manager decision, supplier request, customer communication, or business-state change.</span>
          </div>
        </section>
      )}

      <section className="recovery-demo-timeline" aria-label="Synthetic scenario sequence">
        <div><span>1</span><p><strong>Supplier delay enters the scenario</strong><br />Original and revised ETAs are compared with the material cutoff.</p></div>
        <div><span>2</span><p><strong>Recovery choices are compared</strong><br />Cost, delay, customer impact, assumptions, and unknowns stay visible.</p></div>
        <div><span>3</span><p><strong>Human decision remains open</strong><br />Revalidation, authorized review, supplier confirmation, and any customer acceptance would be separate later facts.</p></div>
      </section>
    </main>
  );
}

function EvidenceRefs({ refs }: { refs: readonly string[] }) {
  return (
    <span className="recovery-evidence-list">
      {refs.map((ref) => <span className="recovery-evidence-chip" key={ref}>{ref}</span>)}
    </span>
  );
}
