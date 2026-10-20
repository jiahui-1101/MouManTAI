import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./layout/AppShell";
import { FeaturePlaceholder } from "./pages/FeaturePlaceholder";
import { OverviewPage } from "./pages/OverviewPage";

export function App() {
  return (
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
  );
}
