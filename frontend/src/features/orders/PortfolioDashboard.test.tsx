import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
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
