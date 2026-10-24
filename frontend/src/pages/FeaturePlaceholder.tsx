import { Link } from "react-router-dom";

interface FeaturePlaceholderProps {
  owner: string;
  title: string;
  description?: string;
}

export function FeaturePlaceholder({ owner, title, description }: FeaturePlaceholderProps) {
  // Helpful context-aware guidance for unmounted / proposed / contract-pending routes
  const getContextualHelp = () => {
    switch (title.toLowerCase()) {
      case "emergency cases":
      case "recovery plans":
        return {
          statusLabel: "BACKEND CONTRACT PENDING (R-06)",
          statusType: "warning",
          note: "Global incident / emergency case list route is not provided by backend. This route is reserved for the owning full-stack feature.",
          links: [
            { label: "View Commitment Recovery Case (rec_001)", to: "/recovery/rec_001" },
            { label: "View Recovery Plans (rec_001)", to: "/recovery/rec_001/plans" },
          ],
        };
      case "all orders":
      case "pending acceptance":
        return {
          statusLabel: "OWNER MODULE PENDING (TRACK B)",
          statusType: "warning",
          note: "Authoritative multi-order queue is pending Track B module delivery. Individual order extraction and context details are active.",
          links: [
            { label: "View Sample Order Context (ord_101)", to: "/orders/ord_101" },
            { label: "View Incoming Messages (Inbox)", to: "/inbox" },
          ],
        };
      case "feasibility":
      case "portfolio comparison":
      case "forecasts":
        return {
          statusLabel: title.toLowerCase() === "feasibility" ? "ACTIVE PER COMMITMENT" : "PROPOSED FEATURE (FE-FORE-01/02)",
          statusType: title.toLowerCase() === "feasibility" ? "info" : "neutral",
          note: title.toLowerCase() === "feasibility"
            ? "Commitment feasibility analysis is available per commitment ID. This route is reserved for the owning full-stack feature."
            : "Multi-order portfolio comparison and predictive forecasting are PROPOSED capabilities. This route is reserved for the owning full-stack feature.",
          links: [
            { label: "View Commitment Feasibility (com_001)", to: "/commitments/com_001" },
            { label: "View Operational Impact (fa_001)", to: "/impact/fa_001" },
          ],
        };
      case "decision history":
        return {
          statusLabel: "PROPOSED FEATURE (FE-MEM-01 / R-11)",
          statusType: "neutral",
          note: "Decision Memory is a PROPOSED capability awaiting verified historical outcome contracts. This route is reserved for the owning full-stack feature.",
          links: [
            { label: "View Activity & Audit History", to: "/activity" },
            { label: "View Daily Performance", to: "/insights/performance" },
          ],
        };
      case "calendar":
        return {
          statusLabel: "OWNER MODULE PENDING (TRACK B)",
          statusType: "warning",
          note: "Production and delivery calendar is pending Track B portfolio integration.",
          links: [
            { label: "View Commitment Overview", to: "/overview" },
          ],
        };
      case "sourcing":
        return {
          statusLabel: "PROPOSED FEATURE (FE-SUP-03 RFQ)",
          statusType: "neutral",
          note: "Direct RFQ sourcing is a PROPOSED extension. This route is reserved for the owning full-stack feature.",
          links: [
            { label: "View Supplier Directory", to: "/suppliers" },
            { label: "View Offer Comparison", to: "/suppliers/compare" },
          ],
        };
      case "settings":
        return {
          statusLabel: "PROPOSED SETTINGS (FE-SET-01)",
          statusType: "neutral",
          note: "Tenant and business policy configuration will be managed here. This route is reserved for the owning full-stack feature.",
          links: [
            { label: "Return to Overview", to: "/overview" },
          ],
        };
      case "page not found":
        return {
          statusLabel: "404 NOT FOUND",
          statusType: "error",
          note: "The requested route does not exist or has been relocated.",
          links: [
            { label: "Return to Overview", to: "/overview" },
          ],
        };
      default:
        return {
          statusLabel: "OWNER MODULE PENDING",
          statusType: "warning",
          note: "This route is reserved for the owning full-stack feature. Phase 0 does not implement it.",
          links: [
            { label: "Return to Overview", to: "/overview" },
          ],
        };
    }
  };

  const help = getContextualHelp();

  return (
    <div className="orbyte-submenu-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">{owner}</p>
          <h2 id="placeholder-title">{title}</h2>
          <p className="muted">
            {description ?? `Manage and review ${title.toLowerCase()} records and platform workflows.`}
          </p>
        </div>
      </header>

      <section aria-labelledby="placeholder-title" className="placeholder-card" style={{ maxWidth: "680px", margin: "24px auto" }}>
        <div style={{ marginBottom: "16px" }}>
          <span className={`status-pill ${help.statusType}`} data-testid="placeholder-status-pill">
            {help.statusLabel}
          </span>
        </div>
        <p className="muted" style={{ lineHeight: 1.6, marginBottom: "24px" }}>
          {help.note}
        </p>

        {help.links.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "10px", alignItems: "center" }}>
            <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--ui-muted)" }}>Available Functional Destinations:</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", justifyContent: "center" }}>
              {help.links.map((link) => (
                <Link key={link.to} to={link.to} className="btn btn-outline btn-sm" style={{ textDecoration: "none" }}>
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
