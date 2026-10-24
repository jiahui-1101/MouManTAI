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

import { PortfolioComparisonMatrix } from './PortfolioComparisonMatrix';
it('shows a fixed three-strategy matrix, preserving redaction and unknown scope without arithmetic', () => {
 const data=portfolioFixture(); data.scenarios[1].metrics.profit!.state='REDACTED'; data.scenarios[1].metrics.profit!.value='987654';
 render(<PortfolioComparisonMatrix data={data} scenarios={data.scenarios} now={Date.parse('2026-10-24T03:00:00Z')} />);
 expect(screen.getByRole('columnheader',{name:'Profit-first'})).toBeInTheDocument();
 expect(screen.getByRole('columnheader',{name:'Expiry-aware'})).toBeInTheDocument();
 expect(screen.getByText('Redacted')).toBeInTheDocument();
 expect(screen.getByRole('rowheader',{name:'Profit Difference'}).parentElement).toHaveTextContent('Unavailable');
 expect(document.body).not.toHaveTextContent('987654');
 expect(screen.getByText(/Matching snapshot versions alone/)).toBeInTheDocument();
});

import { MemoryRouter } from 'react-router-dom';
import { PortfolioAllocationPanel } from './PortfolioAllocationPanel';
it('uses only source order IDs for drilldown and preserves missing quantity and run information', () => {
 const data=portfolioFixture(); render(<MemoryRouter><PortfolioAllocationPanel data={data} scenario={data.scenarios[0]} now={Date.parse('2026-10-24T03:00:00Z')} /></MemoryRouter>);
 expect(screen.getByRole('link',{name:'View Details for one'})).toHaveAttribute('href','/orders/one');
 expect(screen.getByText('Include')).toBeInTheDocument(); expect(screen.getByText('Defer')).toBeInTheDocument(); expect(screen.getByText('Exclude')).toBeInTheDocument();
 expect(screen.getAllByText('Unavailable · quantity contract missing')).toHaveLength(3);
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it.each(['INFEASIBLE','MODEL_INVALID','SOLVER_UNAVAILABLE'])('does not present allocations or profit as usable for %s', status => {
 const data=portfolioFixture(); data.scenarios[0].solverStatus=status;
 render(<MemoryRouter><PortfolioAllocationPanel data={data} scenario={data.scenarios[0]} now={Date.parse('2026-10-24T03:00:00Z')} /></MemoryRouter>);
 expect(screen.queryByRole('table')).not.toBeInTheDocument(); expect(screen.getByText(/Allocation withheld/)).toBeInTheDocument();
});

import { PortfolioSolverExplanation } from './PortfolioSolverExplanation';
it('shows dependency categories without classifying prose as authoritative evidence', () => {
 render(<PortfolioSolverExplanation now={Date.now()} />);
 expect(screen.getByText('Solver explanation is not available.')).toBeInTheDocument();
 for(const name of ['Inventory Constraints','Capacity Constraints','Expiry Constraints','Delivery Constraints']) expect(screen.getByRole('heading',{name})).toBeInTheDocument();
 expect(screen.queryByRole('button')).not.toBeInTheDocument();
});
it('binds source recommendations to the selected scenario rather than inventing explanations', () => {
 const data=portfolioFixture();data.integrationMode='LIVE';data.evidenceTier='VALIDATED';
 const view=render(<PortfolioSolverExplanation data={data} scenario={data.scenarios[0]} now={Date.parse('2026-10-24T03:00:00Z')} />);
 expect(screen.queryByText('Source-provided trade-off explanation')).not.toBeInTheDocument();
 view.rerender(<PortfolioSolverExplanation data={data} scenario={data.scenarios[1]} now={Date.parse('2026-10-24T03:00:00Z')} />);
 expect(screen.getByText('Source-provided trade-off explanation')).toBeInTheDocument();
 expect(screen.getByText(/Explanation source:/)).toBeInTheDocument();
});
