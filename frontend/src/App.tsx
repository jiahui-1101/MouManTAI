import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppShell } from "./layout/AppShell";
import { FeaturePlaceholder } from "./pages/FeaturePlaceholder";
import { OverviewPage } from "./features/overview/OverviewPage";
import { AuthProvider } from "./shared/auth";

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
              <Route path="/activity" element={<FeaturePlaceholder owner="P5 · Shared core" title="Activity and audit" />} />
              <Route path="/inbox" element={<FeaturePlaceholder owner="P1 · Context" title="Smart inbox" />} />
              <Route path="/orders/:id" element={<FeaturePlaceholder owner="P1 · Context" title="Order context" />} />
              <Route path="/commitments/:id" element={<FeaturePlaceholder owner="P2 · Feasibility" title="Commitment feasibility" />} />
              <Route path="/impact/:id" element={<FeaturePlaceholder owner="P2 · Feasibility" title="Operational impact" />} />
              <Route path="/recovery/:id" element={<FeaturePlaceholder owner="P3 · Recovery" title="Recovery case" />} />
              <Route path="/communications" element={<FeaturePlaceholder owner="P4 · Communication" title="Communication center" />} />
              <Route path="/confirmations/:id" element={<FeaturePlaceholder owner="P4 · Communication" title="Confirmation workspace" />} />
              <Route path="*" element={<FeaturePlaceholder owner="Shared shell" title="Page not found" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
