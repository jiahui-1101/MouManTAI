import { useEffect, useMemo, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppShell } from "./layout/AppShell";
import { FeaturePlaceholder } from "./pages/FeaturePlaceholder";
import { OverviewPage } from "./features/overview/OverviewPage";
import { ActivityPage } from "./features/activity/ActivityPage";
import { CommunicationCenterPage } from "./features/communication/CommunicationCenterPage";
import { ConfirmationWorkspacePage } from "./features/communication/ConfirmationWorkspacePage";
import { FollowUpQueuePage } from "./features/communication/FollowUpQueuePage";
import { DurableInbox } from "./features/context/DurableInbox";
import { OrderDetailPage } from "./features/orders/OrderDetailPage";
import { OrderQueuePage } from "./features/orders/OrderQueuePage";
import { PortfolioComparisonPage } from "./features/orders/PortfolioComparisonPage";
import { CalendarSchedulingPage } from "./features/orders/CalendarSchedulingPage";
import { HumanReviewPage } from "./features/context/HumanReviewPage";
import { AuthProvider, useAuth } from "./shared/auth";
import { apiRequest, authHeaders } from "./shared/api";
import { createP2PublicApiSource } from "./features/feasibility/apiSource";
import { CommitmentFeasibilityPage } from "./features/feasibility/CommitmentFeasibilityPage";
import { ImpactDetailPage } from "./features/feasibility/ImpactDetailPage";
import { RecoveryCaseRoutePage } from "./features/recovery/RecoveryCaseRoutePage";
import { RecoveryPage } from "./features/recovery/RecoveryPage";
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

  useEffect(() => {
    const refreshLinkedViews = () => { void defaultClient.invalidateQueries(); };
    window.addEventListener('moumantai:review-context-saved', refreshLinkedViews);
    return () => window.removeEventListener('moumantai:review-context-saved', refreshLinkedViews);
  }, [defaultClient]);

  return (
    <QueryClientProvider client={defaultClient}>
      <AuthProvider initialTenantId={initialTenantId} initialActorId={initialActorId}>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/overview" element={<OverviewPage />} />
              <Route path="/calendar" element={<CalendarSchedulingPage />} />
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/inbox" element={<DurableInbox />} />
              <Route path="/inbox/customer-messages" element={<DurableInbox />} />
              <Route path="/inbox/customer-messages/:messageId" element={<DurableInbox />} />
              <Route path="/human-review" element={<HumanReviewPage />} />
<Route path="/human-review/:taskId" element={<HumanReviewPage />} />
<Route path="/inbox/human-review" element={<HumanReviewPage />} />
<Route path="/inbox/human-review/:taskId" element={<HumanReviewPage />} />

<Route path="/orders" element={<OrderQueuePage />} />
<Route path="/orders/pending" element={<OrderQueuePage />} />
<Route path="/orders/portfolio" element={<PortfolioComparisonPage />} />
<Route path="/orders/calendar" element={<CalendarSchedulingPage />} />
<Route path="/orders/:id" element={<OrderDetailPage />} />
              <Route path="/planning" element={<FeaturePlaceholder owner="Planning" title="Planning" />} />
              <Route path="/planning/feasibility" element={<Navigate to="/orders" replace />} />
              <Route path="/planning/portfolio" element={<PortfolioComparisonPage />} />
              <Route path="/planning/forecasts" element={<FeaturePlaceholder owner="Planning" title="Forecasts" />} />
              <Route path="/commitments/:id" element={<CommitmentFeasibilityRoute />} />
              <Route path="/impact/:id" element={<ImpactDetailRoute />} />
              <Route path="/suppliers" element={<SupplierDirectoryPage />} />
              <Route path="/suppliers/compare" element={<SupplierComparisonPage />} />
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
              <Route path="/insights/performance" element={<FeaturePlaceholder owner="Insights" title="Performance" />} />
              <Route path="/insights/history" element={<FeaturePlaceholder owner="Insights" title="Decision History" />} />
              <Route path="/settings" element={<FeaturePlaceholder owner="Settings" title="Settings" />} />
              {/* Older callers may still supply these formerly additive routes. */}
              {routeExtensions.filter(route => !["/orders/portfolio", "/orders/calendar"].includes(route.path)).map((route) => (
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
