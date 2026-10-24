export interface VersionConflictBannerProps {
  message?: string;
  currentVersion?: string | number;
  expectedVersion?: string | number;
  onRefresh?: () => void;
  refreshing?: boolean;
}

export function VersionConflictBanner({
  message = "This record changed after it was loaded. The displayed version may be out of date.",
  currentVersion,
  expectedVersion,
  onRefresh,
  refreshing = false,
}: VersionConflictBannerProps) {
  return (
    <section className="foundation-conflict" role="alert" aria-labelledby="version-conflict-title">
      <div>
        <h3 id="version-conflict-title">This record has changed</h3>
        <p>{message}</p>
        {(currentVersion !== undefined || expectedVersion !== undefined) && (
          <p className="foundation-conflict-versions">
            {expectedVersion !== undefined && <span>Displayed version: {expectedVersion}</span>}
            {currentVersion !== undefined && <span>Latest server version: {currentVersion}</span>}
          </p>
        )}
      </div>
      {onRefresh && (
        <button className="foundation-button foundation-button-secondary" type="button" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing…" : "Refresh latest version"}
        </button>
      )}
    </section>
  );
}
