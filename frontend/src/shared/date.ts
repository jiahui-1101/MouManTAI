/**
 * Date and time formatting utilities for MouManTAI.
 * Primary SME business operations are reflected in Malaysia time (Asia/Kuala_Lumpur, UTC+8).
 */

export function formatKLTimestamp(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  try {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;
    const formatted = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kuala_Lumpur",
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date);
    return `${formatted} (MYT)`;
  } catch {
    return isoString;
  }
}

export function formatKLDateOnly(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  try {
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return isoString;
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kuala_Lumpur",
      year: "numeric",
      month: "short",
      day: "2-digit",
    }).format(date);
  } catch {
    return isoString;
  }
}
