import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ExtractionProvenance } from './ExtractionProvenance';
import type { ExtractionAttemptRecord } from './types';

const attempt = { fields: [], diagnostic: null } as unknown as ExtractionAttemptRecord;
describe('honest extraction provenance', () => {
  it('distinguishes reused cached observations from a fresh worker call', () => {
    render(<ExtractionProvenance attempt={{ ...attempt, extractor_version: 'p1-ai-pipeline-v2', diagnostic: JSON.stringify({
      runtime_reported: { gliner: { attempted: false, succeeded: true, cached: true } },
    }) }} />);
    expect(screen.getByText(/cached observations reused/)).toBeInTheDocument();
    expect(screen.queryByText(/model call attempted/)).not.toBeInTheDocument();
  });
  it('does not infer GPU or accepted fields from legacy pipeline labels', () => {
    render(<ExtractionProvenance attempt={{ ...attempt, extractor_version: 'p1-ai-pipeline-v1' }} />);
    expect(screen.getByText(/GPU unverified/)).toBeInTheDocument();
    expect(screen.queryByText(/Tesla T4/)).not.toBeInTheDocument();
    expect(screen.getByText('RULES · NO ACCEPTED MODEL FIELDS')).toBeInTheDocument();
  });
  it('labels runtime device information as reported, and distinguishes successful inference', () => {
    render(<ExtractionProvenance attempt={{ ...attempt, diagnostic: JSON.stringify({ configured: true,
      accepted_model_fields: 0, runtime_reported: { gliner: { attempted: true, succeeded: true, device: 'Tesla T4' } } }) }} />);
    expect(screen.getByText(/not independently attested/)).toBeInTheDocument();
    expect(screen.getByText(/inference response validated/)).toBeInTheDocument();
    expect(screen.queryByText('GPU Acceleration Active')).not.toBeInTheDocument();
  });
  it('shows model outage and retained rules without GPU success', () => {
    render(<ExtractionProvenance attempt={{ ...attempt, diagnostic: JSON.stringify({fallback: 'rules_only',
      model_outcomes: {qwen: 'timeout'}, runtime_reported: {qwen: {attempted: true, succeeded: false}}}) }} />);
    expect(screen.getByText(/inference unsuccessful/)).toBeInTheDocument();
    expect(screen.getByText(/RULE \(FALLBACK\)/)).toBeInTheDocument();
  });
});
