import type { AppRouteRegistration } from '../../App';
import { PortfolioComparisonPage } from './PortfolioComparisonPage';

/** Developer C can append these registrations to existing App.routeExtensions. */
export const orderPlanningRoutes: readonly AppRouteRegistration[] = [
  { path: '/orders/portfolio', element: <PortfolioComparisonPage /> },
];
