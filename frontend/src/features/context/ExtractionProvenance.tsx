import type { ExtractionAttemptRecord } from './types';

export function ExtractionProvenance({ attempt }: { attempt: ExtractionAttemptRecord }) {
  let diagnostic: Record<string, unknown> = {};
  try { diagnostic = JSON.parse(attempt.diagnostic ?? '{}'); } catch { /* Legacy diagnostics are unverified. */ }
  const runtime = diagnostic.runtime_reported as Record<string, { attempted?: boolean; succeeded?: boolean; device?: string; model?: string; inference_seconds?: number }> | undefined;
  const outcomes = diagnostic.model_outcomes as Record<string, string> | undefined;
  const modelFields = (attempt.fields ?? []).filter(f => f.evidence?.some(e => e.method === 'MODEL'));
  const accepted = typeof diagnostic.accepted_model_fields === 'number' ? diagnostic.accepted_model_fields : 0;
  return <div className="p1-provenance" aria-label="Extraction provenance">
    <p><strong>Method:</strong> <span className="p1-badge p1-blue">{accepted > 0 ? 'MODEL CONTRIBUTED ACCEPTED FIELDS' : 'RULES · NO ACCEPTED MODEL FIELDS'}</span></p>
    <p>Pipeline version: {attempt.extractor_version}</p>
    {diagnostic.configured === true && <p>AI configured · configuration alone does not prove inference.</p>}
    {Object.entries(outcomes ?? {}).map(([engine, outcome]) => <p key={engine}>{engine}: {outcome === 'not_needed' ? 'not called — rules sufficient or trusted metadata required' : outcome}</p>)}
    {Object.entries(runtime ?? {}).map(([engine, value]) => <p key={engine}>
      {engine}: {value.attempted ? 'model call attempted' : 'not called'} · {value.succeeded ? 'inference response validated' : 'inference unsuccessful'}
      {value.model ? ` · ${value.model}` : ''}{typeof value.inference_seconds === 'number' ? ` · ${value.inference_seconds.toFixed(3)}s reported` : ''}
      {value.device ? ` · device reported by endpoint: ${value.device} (not independently attested)` : ' · GPU unverified'}
    </p>)}
    {!runtime && <p>GPU unverified · historical attempt has no persisted runtime telemetry.</p>}
    {modelFields.length > 0 && <p>Model observations: {modelFields.length} · provisional/rejected observations do not establish accepted fields. Manual review required.</p>}
    {Boolean(diagnostic.fallback) && <p>RULE (FALLBACK) · deterministic results preserved.</p>}
    {Boolean(diagnostic.source_clock_anomaly) && <p role="alert">Source receipt is later than server persistence. Original timestamps preserved; review source clock.</p>}
  </div>;
}
