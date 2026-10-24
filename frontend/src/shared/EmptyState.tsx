import type { ReactNode } from "react";

export type EmptyStateKind = "empty" | "no-results" | "unavailable" | "not-measured";

export interface EmptyStateProps {
  kind: EmptyStateKind;
  title: string;
  description: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

const KIND_LABEL: Record<EmptyStateKind, string> = {
  empty: "No records",
  "no-results": "No matching results",
  unavailable: "Data unavailable",
  "not-measured": "Not measured",
};

export function EmptyState({ kind, title, description, icon, action, className = "" }: EmptyStateProps) {
  return (
    <section className={`foundation-empty ${className}`.trim()} aria-label={KIND_LABEL[kind]}>
      {icon && <span className="foundation-empty-icon" aria-hidden="true">{icon}</span>}
      <p className="foundation-eyebrow">{KIND_LABEL[kind]}</p>
      <h3>{title}</h3>
      <p>{description}</p>
      {action && <div className="foundation-empty-action">{action}</div>}
    </section>
  );
}
