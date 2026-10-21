interface FeaturePlaceholderProps {
  owner: string;
  title: string;
}

export function FeaturePlaceholder({ owner, title }: FeaturePlaceholderProps) {
  return (
    <section aria-labelledby="placeholder-title" className="placeholder-card">
      <p className="eyebrow">{owner}</p>
      <h2 id="placeholder-title">{title}</h2>
      <p className="muted">This route is reserved for the owning full-stack feature. Phase 0 does not implement it.</p>
      <span className="status-pill warning">OWNER MODULE PENDING</span>
    </section>
  );
}
