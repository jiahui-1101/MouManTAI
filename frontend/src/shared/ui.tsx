import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <button type="button" className={`btn btn-${variant} ${className}`.trim()} {...props} />;
}

export function PageHeader({ title, description, actions, children }: { title: string; description?: string; actions?: ReactNode; children?: ReactNode }) {
  return <header className="ui-page-header"><div><h2>{title}</h2>{description && <p>{description}</p>}{children}</div>{actions && <div className="ui-page-actions">{actions}</div>}</header>;
}

export function ContentCard({ title, actions, children, className = "", ...props }: HTMLAttributes<HTMLElement> & { title?: string; actions?: ReactNode }) {
  return <section className={`ui-card ${className}`.trim()} {...props}>{(title || actions) && <div className="ui-card-header">{title && <h3>{title}</h3>}{actions}</div>}{children}</section>;
}

export function KPIStatCard({ label, value, detail, children }: { label: string; value: ReactNode; detail?: string; children?: ReactNode }) {
  return <ContentCard className="ui-kpi"><strong className="ui-kpi-value">{value}</strong><span className="ui-kpi-label">{label}</span>{detail && <small>{detail}</small>}{children}</ContentCard>;
}

export function SearchField({ label, id, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { label: string; id: string }) {
  return <label className="ui-field" htmlFor={id}><span>{label}</span><input id={id} type="search" {...props} /></label>;
}

export function DataTable({ children, className = "", ...props }: HTMLAttributes<HTMLTableElement>) {
  return <div className="ui-table-scroll"><table className={`ui-table ${className}`.trim()} {...props}>{children}</table></div>;
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="ui-state ui-empty"><h3>{title}</h3>{description && <p>{description}</p>}{action}</div>;
}

export function ErrorState({ title = "Unable to load", description, onRetry }: { title?: string; description?: string; onRetry?: () => void }) {
  return <div className="ui-state ui-error" role="alert"><h3>{title}</h3>{description && <p>{description}</p>}{onRetry && <Button onClick={onRetry}>Retry</Button>}</div>;
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return <div className="ui-state" role="status" aria-busy="true">{label}</div>;
}

export function ProgressBar({ value, max = 100, label }: { value: number; max?: number; label: string }) {
  const safeMax = max > 0 ? max : 100;
  const safeValue = Math.max(0, Math.min(value, safeMax));
  return <div className="ui-progress"><div className="ui-progress-label"><span>{label}</span><strong>{safeValue} / {safeMax}</strong></div><progress value={safeValue} max={safeMax} aria-label={label} /></div>;
}
