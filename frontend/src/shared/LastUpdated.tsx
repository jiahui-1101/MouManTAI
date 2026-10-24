import { formatKLTimestamp } from "./date";

export interface LastUpdatedProps {
  value?: string | null;
  label?: string;
  timeZone?: string;
  className?: string;
}

const OFFSET_AWARE_ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/i;

export function LastUpdated({
  value,
  label = "Last updated",
  timeZone = "Asia/Kuala_Lumpur",
  className = "",
}: LastUpdatedProps) {
  if (!value || !OFFSET_AWARE_ISO.test(value) || Number.isNaN(Date.parse(value))) {
    return <span className={`foundation-last-updated ${className}`.trim()} aria-label={`${label}: unknown`}>{label}: unknown</span>;
  }

  const formatted = formatKLTimestamp(value, timeZone);
  return (
    <span className={`foundation-last-updated ${className}`.trim()}>
      {label}: <time dateTime={value} aria-label={formatted}>{formatted}</time>
    </span>
  );
}
