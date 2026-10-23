import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { orderPlanningRoutes } from "./features/orders/portfolioRoutes";
import "./styles.css";
import "./shared/foundation.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App routeExtensions={orderPlanningRoutes} />
  </StrictMode>,
);
