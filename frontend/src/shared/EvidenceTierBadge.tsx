import type { HTMLAttributes } from "react";

export type EvidenceTier = "TARGET" | "DEMO-ONLY" | "VALIDATED" | "LIVE";
export type IntegrationMode = "SYNTHETIC" | "MOCK_ORBYTE" | "LIVE";

type EvidenceTierBadgeBaseProps = Omit<HTMLAttributes<HTMLSpanElement>, "children">;

export type EvidenceTierBadgeProps = EvidenceTierBadgeBaseProps &
  (
    | { evidenceTier: EvidenceTier; integrationMode?: IntegrationMode }
    | { evidenceTier?: EvidenceTier; integrationMode: IntegrationMode }
  );

const evidenceLabels: Record<EvidenceTier, string> = {
  TARGET: "TARGET",
  "DEMO-ONLY": "DEMO-ONLY",
  VALIDATED: "VALIDATED",
  LIVE: "LIVE",
};

const modeLabels: Record<IntegrationMode, string> = {
  SYNTHETIC: "SYNTHETIC",
  MOCK_ORBYTE: "MOCK_ORBYTE",
  LIVE: "LIVE",
};

/** Displays evidence maturity and integration mode as separate facts. */
export function EvidenceTierBadge({
  evidenceTier,
  integrationMode,
  className = "",
  ...props
}: EvidenceTierBadgeProps) {
  const parts = [
    evidenceTier ? `Evidence: ${evidenceTier}` : null,
    integrationMode ? `Integration mode: ${integrationMode}` : null,
  ].filter(Boolean);

  return (
    <span
      {...props}
      className={`foundation-evidence-badge ${className}`.trim()}
      aria-label={parts.join("; ")}
      data-evidence-tier={evidenceTier}
      data-integration-mode={integrationMode}
    >
      {evidenceTier && <span className={`foundation-evidence-tier evidence-${evidenceTier.toLowerCase()}`}>{evidenceLabels[evidenceTier]}</span>}
      {integrationMode && <span className={`foundation-integration-mode mode-${integrationMode.toLowerCase()}`}>{modeLabels[integrationMode]}</span>}
    </span>
  );
}
