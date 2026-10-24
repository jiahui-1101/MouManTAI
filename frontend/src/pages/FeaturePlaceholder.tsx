interface FeaturePlaceholderProps {
  owner: string;
  title: string;
}

export function FeaturePlaceholder({ owner, title }: FeaturePlaceholderProps) {
  return (
    <div className="orbyte-submenu-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">{owner}</p>
          <h2 id="placeholder-title">{title}</h2>
          <p className="muted">Manage and review {title.toLowerCase()} records and platform workflows.</p>
        </div>
      </header>

      <section aria-labelledby="placeholder-title" className="placeholder-card">
        <p className="muted">This route is reserved for the owning full-stack feature. Phase 0 does not implement it.</p>
        <div style={{ marginTop: "16px" }}>
          <span className="status-pill warning">OWNER MODULE PENDING</span>
        </div>
      </section>
    </div>
  );
}
