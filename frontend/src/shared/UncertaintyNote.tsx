import type { ReactNode } from "react";

export type UncertaintyKind = "unknown" | "conditional" | "insufficient-evidence" | "unverified-claim" | "freshness";

export interface UncertaintyNoteProps {
  kind: UncertaintyKind;
  children: ReactNode;
  className?: string;
}

const LABEL: Record<UncertaintyKind, string> = {
  unknown: "Unknown",
  conditional: "Conditional",
  "insufficient-evidence": "Insufficient evidence",
  "unverified-claim": "Unverified claim",
  freshness: "Data freshness",
};

export function UncertaintyNote({ kind, children, className = "" }: UncertaintyNoteProps) {
  return (
    <aside className={`foundation-uncertainty uncertainty-${kind} ${className}`.trim()} role="note" aria-label={LABEL[kind]}>
      <strong>{LABEL[kind]}</strong>
      <span>{children}</span>
    </aside>
  );
}
