import type { ExtractionAttemptRecord } from './types';

export function ExtractionProvenance({ attempt }: { attempt: ExtractionAttemptRecord }) {
  let diagnostic: Record<string, unknown> = {};
  try { diagnostic = JSON.parse(attempt.diagnostic ?? '{}'); } catch { /* Legacy diagnostics are unverified. */ }

  const runtime = diagnostic.runtime_reported as Record<string, { attempted?: boolean; succeeded?: boolean; cached?: boolean; coalesced?: boolean; device?: string; model?: string; inference_seconds?: number }> | undefined;
  const outcomes = diagnostic.model_outcomes as Record<string, string> | undefined;
  const modelFields = (attempt.fields ?? []).filter(f => f.evidence?.some(e => e.method === 'MODEL'));
  const accepted = typeof diagnostic.accepted_model_fields === 'number' ? diagnostic.accepted_model_fields : 0;

  const isExplicitDeterministic = attempt.extractor_version?.startsWith('p1-deterministic-');
  const anyModelAttempted = Object.values(runtime ?? {}).some(v => v.attempted === true);
  const isAiPipeline = (attempt.extractor_version?.startsWith('p1-ai-pipeline-') || anyModelAttempted || Boolean(runtime));

  return (
    <div className="p1-provenance-card" aria-label="Extraction provenance">
      <div className="p1-prov-header">
        <div className="p1-prov-tag-group">
          <span className="p1-prov-label">Decision Policy</span>
          {accepted > 0 ? (
            <span className="p1-badge p1-gpu-badge">MODEL CONTRIBUTED ACCEPTED FIELDS</span>
          ) : isExplicitDeterministic && !anyModelAttempted ? (
            <span className="p1-badge p1-rules-badge">DETERMINISTIC RULES</span>
          ) : (
            <span className="p1-badge p1-blue">RULES · NO ACCEPTED MODEL FIELDS</span>
          )}
        </div>
        <div className="p1-prov-tag-group">
          <span className="p1-prov-chip">Pipeline version: {attempt.extractor_version}</span>
        </div>
      </div>

      {isAiPipeline && (
        <>
          {runtime ? (
            <div className="p1-prov-telemetry-section">
              {Object.entries(runtime).map(([engine, value]) => {
                if (value.cached || value.coalesced) {
                  return <p key={engine}>{engine}: {value.cached ? 'cached observations reused' : 'shared in-flight response reused'} · no new worker call · current validation and review still required</p>;
                }
                if (!value.attempted) {
                  return null;
                }
                return (
                  <div key={engine} className="p1-prov-telemetry-card">
                    <div className="p1-prov-telemetry-top">
                      <span className="p1-prov-engine-tag">{engine.toUpperCase()}</span>
                      <span className={`p1-prov-status-indicator ${value.succeeded ? 'is-success' : 'is-failed'}`}>
                        <span className="p1-prov-dot" />
                        model call attempted · {value.succeeded ? 'inference response validated' : 'inference unsuccessful'}
                      </span>
                    </div>
                    <div className="p1-prov-telemetry-grid">
                      <div className="p1-prov-telemetry-item">
                        <span className="p1-prov-metric-label">Compute Device</span>
                        <span className="p1-prov-metric-val">
                          {value.device ? `${value.device} (not independently attested)` : ' · GPU unverified'}
                        </span>
                      </div>
                      {value.model && (
                        <div className="p1-prov-telemetry-item">
                          <span className="p1-prov-metric-label">Model Id</span>
                          <span className="p1-prov-metric-val p1-mono">{value.model}</span>
                        </div>
                      )}
                      {typeof value.inference_seconds === 'number' && (
                        <div className="p1-prov-telemetry-item">
                          <span className="p1-prov-metric-label">Inference Latency</span>
                          <span className="p1-prov-metric-val">{value.inference_seconds.toFixed(3)}s reported</span>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="p1-prov-unverified-box">
              <span className="p1-prov-dot is-amber" />
              <span>GPU unverified · historical attempt has no persisted runtime telemetry.</span>
            </div>
          )}

          {anyModelAttempted && (
            <div className="p1-prov-footer-notes">
              {diagnostic.configured === true && (
                <p className="p1-prov-notice">
                  AI configured · configuration alone does not prove inference.
                </p>
              )}
              {Object.entries(outcomes ?? {}).map(([engine, outcome]) => (
                <p key={engine} className="p1-prov-engine-outcome">
                  <strong>{engine}:</strong> {outcome === 'not_needed' ? 'not called — rules sufficient or trusted metadata required' : outcome}
                </p>
              ))}
              {modelFields.length > 0 && (
                <div className="p1-prov-warning-box">
                  Model observations: {modelFields.length} · provisional/rejected observations do not establish accepted fields. Manual review required.
                </div>
              )}
            </div>
          )}
        </>
      )}

      {Boolean(diagnostic.fallback) && (
        <div className="p1-prov-footer-notes">
          <p className="p1-prov-fallback">
            RULE (FALLBACK) · deterministic results preserved.
          </p>
        </div>
      )}

      {Boolean(diagnostic.source_clock_anomaly) && (
        <div className="p1-prov-footer-notes">
          <p role="alert" className="p1-prov-alert">
            Source receipt is later than server persistence. Original timestamps preserved; review source clock.
          </p>
        </div>
      )}
    </div>
  );
}

