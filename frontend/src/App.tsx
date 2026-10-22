import { useMemo, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppShell } from "./layout/AppShell";
import { FeaturePlaceholder } from "./pages/FeaturePlaceholder";
import { OverviewPage } from "./features/overview/OverviewPage";
import { ActivityPage } from "./features/activity/ActivityPage";
import { CommunicationCenterPage } from "./features/communication/CommunicationCenterPage";
import { DurableInbox } from "./features/context/DurableInbox";
import { OrderContextDetail } from "./features/context/OrderContextDetail";
import { AuthProvider, useAuth } from "./shared/auth";
import { apiRequest, authHeaders } from "./shared/api";
import { createP2PublicApiSource } from "./features/feasibility/apiSource";
import { CommitmentFeasibilityPage } from "./features/feasibility/CommitmentFeasibilityPage";
import { ImpactDetailPage } from "./features/feasibility/ImpactDetailPage";

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

export interface AppProps {
  queryClient?: QueryClient;
  initialTenantId?: string;
  initialActorId?: string;
}

export function App({ queryClient, initialTenantId, initialActorId }: AppProps = {}) {
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
              <Route path="/activity" element={<ActivityPage />} />
              <Route path="/inbox" element={<DurableInbox />} />
              <Route path="/orders/:id" element={<OrderContextDetail />} />
              <Route path="/commitments/:id" element={<CommitmentFeasibilityRoute />} />
              <Route path="/impact/:id" element={<ImpactDetailRoute />} />
              <Route path="/recovery/:id" element={<FeaturePlaceholder owner="P3 · Recovery" title="Recovery case" />} />
              <Route path="/communications" element={<CommunicationCenterPage />} />
              <Route path="/confirmations/:id" element={<FeaturePlaceholder owner="P4 · Communication" title="Confirmation workspace" />} />
              <Route path="*" element={<FeaturePlaceholder owner="Shared shell" title="Page not found" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
