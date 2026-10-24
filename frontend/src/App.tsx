import { useMemo, useState, type ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppShell } from "./layout/AppShell";
import { FeaturePlaceholder } from "./pages/FeaturePlaceholder";
import { OverviewPage } from "./features/overview/OverviewPage";
import { ActivityPage } from "./features/activity/ActivityPage";
import { CommunicationCenterPage } from "./features/communication/CommunicationCenterPage";
import { ConfirmationWorkspacePage } from "./features/communication/ConfirmationWorkspacePage";
import { FollowUpQueuePage } from "./features/communication/FollowUpQueuePage";
import { DurableInbox } from "./features/context/DurableInbox";
import { HumanReviewPage } from "./features/context/HumanReviewPage";
import { OrderContextDetail } from "./features/context/OrderContextDetail";
import { AuthProvider, useAuth } from "./shared/auth";
import { apiRequest, authHeaders } from "./shared/api";
import { createP2PublicApiSource } from "./features/feasibility/apiSource";
import { CommitmentFeasibilityPage } from "./features/feasibility/CommitmentFeasibilityPage";
import { ImpactDetailPage } from "./features/feasibility/ImpactDetailPage";
import { RecoveryCaseRoutePage } from "./features/recovery/RecoveryCaseRoutePage";
import { RecoveryPage } from "./features/recovery/RecoveryPage";
import { DailyPerformancePage } from "./features/overview/DailyPerformance";
import { SupplierComparisonPage, SupplierDetailPage, SupplierDirectoryPage } from "./features/suppliers/SupplierWorkspace";

export function CommitmentFeasibilityRoute() {
  const { authHeaders: auth } = useAuth();
  const source = useMemo(
    () =>
      createP2PublicApiSource(auth.tenantId, (path, init) =>
        apiRequest(path, {
          ...init,
          headers: {
            ...authHeaders(auth),
            ...init?.headers,
          },
        }),
      ),
    [auth],
  );
  return <CommitmentFeasibilityPage source={source} />;
}

export function ImpactDetailRoute() {
  const { authHeaders: auth } = useAuth();
  const source = useMemo(
    () =>
      createP2PublicApiSource(auth.tenantId, (path, init) =>
        apiRequest(path, {
          ...init,
          headers: {
            ...authHeaders(auth),
            ...init?.headers,
          },
        }),
      ),
    [auth],
  );
  return <ImpactDetailPage source={source} />;
}

export interface AppRouteRegistration {
  path: string;
  element: ReactNode;
}

export interface AppProps {
  queryClient?: QueryClient;
  initialTenantId?: string;
  initialActorId?: string;
  /** Additional exact-path page registrations for the shared shell integration pass. */
  routeExtensions?: readonly AppRouteRegistration[];
}

export function App({ queryClient, initialTenantId, initialActorId, routeExtensions = [] }: AppProps = {}) {
  const [defaultClient] = useState(
    () =>
      queryClient ??
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={defaultClient}>
      <AuthProvider initialTenantId={initialTenantId} initialActorId={initialActorId}>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/overview" element={<OverviewPage />} />
              <Route path="/calendar" element={<FeaturePlaceholder owner="Shared shell" title="Calendar" />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/inbox" element={<DurableInbox />} />
              <Route path="/human-review" element={<HumanReviewPage />} />
              <Route path="/orders" element={<FeaturePlaceholder owner="Orders" title="All Orders" />} />
              <Route path="/orders/pending" element={<FeaturePlaceholder owner="Orders" title="Pending Acceptance" />} />
              <Route path="/orders/:id" element={<OrderContextDetail />} />
              <Route path="/planning" element={<FeaturePlaceholder owner="Planning" title="Planning" />} />
              <Route path="/planning/feasibility" element={<FeaturePlaceholder owner="Planning" title="Feasibility" />} />
              <Route path="/planning/portfolio" element={<FeaturePlaceholder owner="Planning" title="Portfolio Comparison" />} />
              <Route path="/planning/forecasts" element={<FeaturePlaceholder owner="Planning" title="Forecasts" />} />
              <Route path="/commitments/:id" element={<CommitmentFeasibilityRoute />} />
              <Route path="/impact/:id" element={<ImpactDetailRoute />} />
              <Route path="/suppliers" element={<SupplierDirectoryPage />} />
              <Route path="/suppliers/compare" element={<SupplierComparisonPage />} />
              <Route path="/supplier-comparison" element={<SupplierComparisonPage />} />
              <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
              <Route path="/suppliers/sourcing" element={<FeaturePlaceholder owner="Suppliers" title="Sourcing" />} />
              <Route path="/recovery" element={<FeaturePlaceholder owner="Recovery" title="Emergency Cases" />} />
              <Route path="/recovery/plans" element={<FeaturePlaceholder owner="Recovery" title="Recovery Plans" />} />
              <Route path="/recovery/:id/plans" element={<RecoveryPage />} />
              <Route path="/recovery/:id" element={<RecoveryCaseRoutePage />} />
              <Route path="/communications" element={<CommunicationCenterPage />} />
              <Route path="/confirmations/:id" element={<ConfirmationWorkspacePage />} />
              <Route path="/communications/follow-ups" element={<FollowUpQueuePage />}/>
              <Route path="/insights" element={<FeaturePlaceholder owner="Insights" title="Insights" />} />
              <Route path="/insights/performance" element={<DailyPerformancePage />} />
              <Route path="/performance" element={<DailyPerformancePage />} />
              <Route path="/insights/history" element={<FeaturePlaceholder owner="Insights" title="Decision History" />} />
              <Route path="/settings" element={<FeaturePlaceholder owner="Settings" title="Settings" />} />
              {routeExtensions.map((route) => (
                <Route key={route.path} path={route.path} element={route.element} />
              ))}
              <Route path="*" element={<FeaturePlaceholder owner="Shared shell" title="Page not found" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
