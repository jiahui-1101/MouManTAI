export type TimelineStatus = "completed" | "current" | "pending" | "failed";

export interface TimelineStage {
  id: string;
  label: string;
  status: TimelineStatus;
  timestamp?: string | null;
  description?: string;
  evidenceRefs?: string[];
}

export interface StateTimelineProps {
  stages: TimelineStage[];
  label?: string;
  className?: string;
}

const STATUS_LABEL: Record<TimelineStatus, string> = {
  completed: "Completed",
  current: "Current",
  pending: "Pending",
  failed: "Failed",
};

export function StateTimeline({ stages, label = "State timeline", className = "" }: StateTimelineProps) {
  return (
    <ol className={`foundation-timeline ${className}`.trim()} aria-label={label}>
      {stages.map((stage) => {
        const timeIsAware = !!stage.timestamp && /(?:Z|[+-]\d{2}:\d{2})$/i.test(stage.timestamp) && !Number.isNaN(Date.parse(stage.timestamp));
        return (
          <li key={stage.id} className={`foundation-timeline-stage timeline-${stage.status}`} data-status={stage.status}>
            <span className="foundation-timeline-marker" aria-hidden="true" />
            <div className="foundation-timeline-content">
              <div className="foundation-timeline-heading">
                <strong>{stage.label}</strong>
                <span className="foundation-timeline-status">{STATUS_LABEL[stage.status]}</span>
              </div>
              {timeIsAware && <time dateTime={stage.timestamp!}>{stage.timestamp}</time>}
              {stage.description && <p>{stage.description}</p>}
              {stage.evidenceRefs && stage.evidenceRefs.length > 0 && (
                <ul className="foundation-timeline-evidence" aria-label={`${stage.label} evidence references`}>
                  {stage.evidenceRefs.map((ref) => <li key={ref}><code>{ref}</code></li>)}
                </ul>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
