import { afterEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { PortfolioAnalysisScope } from './PortfolioAnalysisScope';
import { portfolioFixture } from './portfolioTest.fixtures';
afterEach(cleanup);
it('does not substitute Demo Queue counts for considered orders or manufacture a planning period', () => {
 render(<PortfolioAnalysisScope />);
 expect(screen.getByText('Solver unavailable')).toBeInTheDocument();
 expect(screen.getByText(/solver eligibility not supplied/)).toBeInTheDocument();
 expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it('labels loaded strategy statuses and source time without claiming solver eligibility', () => {
 render(<PortfolioAnalysisScope data={portfolioFixture()} />);
 expect(screen.getByText('FCFS / PROFIT')).toBeInTheDocument();
 expect(screen.getByText('Current verified snapshot')).toBeInTheDocument();
 expect(screen.getByText(/Complete returned snapshot/)).toBeInTheDocument();
});

import { PortfolioStrategyAvailability } from './PortfolioStrategyAvailability';
it('selects only returned strategies and preserves the per-metric profit redaction guard', () => {
 const data=portfolioFixture(); data.scenarios[1].metrics.profit!.state='REDACTED'; data.scenarios[1].metrics.profit!.value='987654';
 let selected=''; render(<PortfolioStrategyAvailability data={data} selectedId="s0" now={Date.parse('2026-10-24T03:00:00Z')} onSelect={id=>{selected=id;}} />);
 expect(screen.getByRole('button',{name:'Select FCFS strategy'})).toHaveAttribute('aria-pressed','true');
 fireEvent.click(screen.getByRole('button',{name:'Select Profit strategy'})); expect(selected).toBe('s1');
 expect(screen.getByRole('button',{name:'Select Expiry-aware strategy'})).toBeDisabled();
 expect(document.body).not.toHaveTextContent('987654');
 expect(screen.queryByText(/Recommended · source-backed/)).not.toBeInTheDocument();
});
