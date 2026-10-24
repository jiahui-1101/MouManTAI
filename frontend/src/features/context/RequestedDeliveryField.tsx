import React, { useState, useMemo, useEffect } from 'react';
import type { OrderContextRecord } from './types';

export interface RequestedDeliveryFieldProps {
  value: string;
  qualifier?: string;
  context?: OrderContextRecord | null;

  onChange: (newValue: string, newQualifier: string) => void;
  onFocus?: () => void;

  onToggleEvidence?: () => void;
  disabled?: boolean;
}

export interface TimezoneOption {
  id: string;
  label: string;
  offset: string;
  code: string;
}

export const TIMEZONE_OPTIONS: TimezoneOption[] = [
  { id: 'Asia/Kuala_Lumpur', label: 'Asia/Kuala_Lumpur (Malaysia Time, UTC+08:00)', offset: '+08:00', code: 'MYT' },
  { id: 'Asia/Singapore', label: 'Asia/Singapore (Singapore Time, UTC+08:00)', offset: '+08:00', code: 'SGT' },
  { id: 'UTC', label: 'UTC (Coordinated Universal Time, UTC+00:00)', offset: 'Z', code: 'UTC' },
];

export const QUALIFIER_OPTIONS = [
  { value: 'DEADLINE', label: 'Deadline (Deliver by / before)' },
  { value: 'EXACT', label: 'Exact delivery time' },
  { value: 'DATE_ONLY', label: 'Date only (Exact time unresolved)' },
  { value: 'UNRESOLVED', label: 'Unresolved' },
  { value: 'Before', label: 'Before' },
  { value: 'After', label: 'After' },
  { value: 'Around', label: 'Around / Approximate' },
];

/**
 * Checks if a string contains an explicit UTC offset (e.g. +08:00, -05:00, or Z)
 */
export function hasExplicitOffset(str: string): boolean {
  return /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(str.trim());
}

/**
 * Parses an existing delivery string into date, time components, and offset.
 */
export function parseDeliveryString(val: string, displayOffset = '+08:00'): {
  date: string;
  hasTime: boolean;
  hour12: string;
  minute: string;
  ampm: 'AM' | 'PM';
  offset: string;
  isDateOnly: boolean;
} {
  const trimmed = val.trim();
  if (!trimmed) {
    return {
      date: '',
      hasTime: false,
      hour12: '10',
      minute: '00',
      ampm: 'AM',
      offset: '+08:00',
      isDateOnly: true,
    };
  }

  // Check if date-only format: YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
    return {
      date: trimmed,
      hasTime: false,
      hour12: '10',
      minute: '00',
      ampm: 'AM',
      offset: '+08:00',
      isDateOnly: true,
    };
  }

  // Match ISO timestamp: YYYY-MM-DDTHH:mm(:ss)?(offset)?
  const match = trimmed.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(Z|[+-]\d{2}(?::?\d{2})?)?$/i);
  if (match) {
    const [, datePart, h24Str, minStr, , offsetPart] = match;
    const requestedOffset = displayOffset === 'Z' ? '+00:00' : displayOffset;
    const offsetMatch = requestedOffset.match(/^([+-])(\d{2}):(\d{2})$/);
    const offsetMinutes = offsetMatch ? (offsetMatch[1] === '-' ? -1 : 1) * (Number(offsetMatch[2]) * 60 + Number(offsetMatch[3])) : 0;
    const instant = offsetPart ? new Date(trimmed) : null;
    const wall = instant && !Number.isNaN(instant.getTime()) ? new Date(instant.getTime() + offsetMinutes * 60_000) : null;
    const displayDate = wall ? wall.toISOString().slice(0, 10) : datePart;
    const h24 = wall ? wall.getUTCHours() : parseInt(h24Str, 10);
    const ampm: 'AM' | 'PM' = h24 >= 12 ? 'PM' : 'AM';
    let h12 = h24 % 12;
    if (h12 === 0) h12 = 12;
    const hour12 = String(h12).padStart(2, '0');
    const minute = wall ? String(wall.getUTCMinutes()).padStart(2, '0') : minStr.padStart(2, '0');
    const offset = displayOffset;

    return {
      date: displayDate,
      hasTime: true,
      hour12,
      minute,
      ampm,
      offset,
      isDateOnly: false,
    };
  }

  // Fallback: try parsing through Date
  const parsed = Date.parse(trimmed);
  if (!isNaN(parsed)) {
    const d = new Date(parsed);
    const date = d.toISOString().slice(0, 10);
    const h24 = d.getUTCHours();
    const ampm: 'AM' | 'PM' = h24 >= 12 ? 'PM' : 'AM';
    let h12 = h24 % 12;
    if (h12 === 0) h12 = 12;
    return {
      date,
      hasTime: true,
      hour12: String(h12).padStart(2, '0'),
      minute: String(d.getUTCMinutes()).padStart(2, '0'),
      ampm,
      offset: '+08:00',
      isDateOnly: false,
    };
  }

  return {
    date: '',
    hasTime: false,
    hour12: '10',
    minute: '00',
    ampm: 'AM',
    offset: '+08:00',
    isDateOnly: true,
  };
}

/**
 * Human-friendly date preview generator
 */
export function formatHumanReadablePreview(
  date: string,
  hasTime: boolean,
  hour12: string,
  minute: string,
  ampm: 'AM' | 'PM',
  timezoneCode: string,
  timezoneOffset: string,
  qualifier: string
): string {
  if (!date) {
    return 'No delivery date selected';
  }

  // Format date parts (e.g. Wednesday, 28 Oct 2026)
  const parts = date.split('-');
  let dateFormatted = date;
  if (parts.length === 3) {
    const [y, m, d] = parts.map(Number);
    const dt = new Date(y, m - 1, d);
    if (!isNaN(dt.getTime())) {
      dateFormatted = dt.toLocaleDateString('en-MY', {
        weekday: 'short',
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      });
    }
  }

  const qualifierLabel =
    qualifier === 'DEADLINE'
      ? 'Deadline'
      : qualifier === 'EXACT'
      ? 'Exact'
      : qualifier === 'DATE_ONLY'
      ? 'Date only'
      : qualifier;

  if (!hasTime || qualifier === 'DATE_ONLY' || qualifier === 'UNRESOLVED') {
    return `${dateFormatted} · ${qualifierLabel} (Exact time unresolved)`;
  }

  return `${dateFormatted} at ${hour12}:${minute} ${ampm} (${timezoneCode}, UTC${timezoneOffset === 'Z' ? '+00:00' : timezoneOffset}) · ${qualifierLabel}`;
}

export function RequestedDeliveryField({
  value,
  qualifier = 'DEADLINE',
  context,
  onChange,
  onFocus,
  onToggleEvidence,
  disabled = false,
}: RequestedDeliveryFieldProps): React.JSX.Element {
  // Parse initial values
  const parsed = useMemo(() => parseDeliveryString(value), [value]);

  const [date, setDate] = useState<string>(parsed.date);
  const [hasTime, setHasTime] = useState<boolean>(() => {
    if (qualifier === 'DATE_ONLY' || qualifier === 'UNRESOLVED') return false;
    return parsed.hasTime;
  });
  const [hour12, setHour12] = useState<string>(parsed.hour12);
  const [minute, setMinute] = useState<string>(parsed.minute);
  const [ampm, setAmPm] = useState<'AM' | 'PM'>(parsed.ampm);
  const [timezoneId, setTimezoneId] = useState<string>('Asia/Kuala_Lumpur');
  const [timingQualifier, setTimingQualifier] = useState<string>(qualifier || 'DEADLINE');
  const [isAdvancedOpen, setIsAdvancedOpen] = useState<boolean>(false);
  const [dismissSuggestion, setDismissSuggestion] = useState<boolean>(false);

  // Sync state if external value changes meaningfully
  useEffect(() => {
    const nextParsed = parseDeliveryString(value, TIMEZONE_OPTIONS.find(t => t.id === timezoneId)?.offset || '+08:00');
    if (nextParsed.date !== date) setDate(nextParsed.date);
    const isDateOnlyOrUnresolved = qualifier === 'DATE_ONLY' || qualifier === 'UNRESOLVED' || qualifier === 'Unresolved';
    if (isDateOnlyOrUnresolved) {
      setHasTime(false);
    } else if (nextParsed.hasTime !== hasTime) {
      setHasTime(nextParsed.hasTime);
    }
    setTimingQualifier(qualifier || 'DEADLINE');
    if (nextParsed.hasTime && !isDateOnlyOrUnresolved) {
      setHour12(nextParsed.hour12);
      setMinute(nextParsed.minute);
      setAmPm(nextParsed.ampm);
    }
  }, [value, qualifier, timezoneId]);

  // Selected timezone
  const selectedTz = useMemo(() => {
    return TIMEZONE_OPTIONS.find(t => t.id === timezoneId) || TIMEZONE_OPTIONS[0];
  }, [timezoneId]);

  // Compute 24h ISO serialization
  const serializedValue = useMemo(() => {
    if (!date) return '';

    // If date-only or time unresolved, do NOT invent midnight clock time!
    if (!hasTime || timingQualifier === 'DATE_ONLY' || timingQualifier === 'UNRESOLVED') {
      return date; // Date-only representation without fabricated 00:00:00!
    }

    let h24 = parseInt(hour12, 10);
    if (ampm === 'PM' && h24 < 12) h24 += 12;
    if (ampm === 'AM' && h24 === 12) h24 = 0;

    const hh = String(h24).padStart(2, '0');
    const mm = minute.padStart(2, '0');
    const ss = '00';
    const offset = selectedTz.offset;

    return `${date}T${hh}:${mm}:${ss}${offset}`;
  }, [date, hasTime, hour12, minute, ampm, selectedTz.offset, timingQualifier]);

  // Propagate changes when user alters form
  const emitChange = (newDate: string, newHasTime: boolean, newH12: string, newMin: string, newAmPm: 'AM' | 'PM', newTzOffset: string, newQual: string) => {
    if (!newDate) {
      onChange('', newQual);
      return;
    }

    if (!newHasTime || newQual === 'DATE_ONLY' || newQual === 'UNRESOLVED') {
      // Date-only: do NOT serialize fabricated midnight timestamp
      onChange(newDate, newQual);
      return;
    }

    let h24 = parseInt(newH12, 10);
    if (newAmPm === 'PM' && h24 < 12) h24 += 12;
    if (newAmPm === 'AM' && h24 === 12) h24 = 0;

    const hh = String(h24).padStart(2, '0');
    const mm = newMin.padStart(2, '0');
    const ss = '00';
    const finalIso = `${newDate}T${hh}:${mm}:${ss}${newTzOffset}`;

    onChange(finalIso, newQual);
  };

  // Inspect source evidence for vague/relative expressions
  const evidence = context?.field_evidence?.requested_delivery_at?.[0] as Record<string, string> | undefined;
  const evidenceQuote: string = String(evidence?.quote || '');
  const isVagueOrRelative = useMemo(() => {
    if (!evidenceQuote) return false;
    return /next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week)|morning|afternoon|evening|around|approx|soon|asap|sometime/i.test(
      evidenceQuote
    );
  }, [evidenceQuote]);

  // Handlers for individual fields
  const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newDate = e.target.value;
    setDate(newDate);
    emitChange(newDate, hasTime, hour12, minute, ampm, selectedTz.offset, timingQualifier);
  };

  const handleToggleExactTime = (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked;
    setHasTime(checked);
    const newQual = checked
      ? timingQualifier === 'DATE_ONLY' ? 'DEADLINE' : timingQualifier
      : 'DATE_ONLY';
    setTimingQualifier(newQual);
    emitChange(date, checked, hour12, minute, ampm, selectedTz.offset, newQual);
  };

  const handleHourChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newH = e.target.value;
    setHour12(newH);
    emitChange(date, hasTime, newH, minute, ampm, selectedTz.offset, timingQualifier);
  };

  const handleMinuteChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newMin = e.target.value;
    setMinute(newMin);
    emitChange(date, hasTime, hour12, newMin, ampm, selectedTz.offset, timingQualifier);
  };

  const handleAmPmToggle = (newAmPm: 'AM' | 'PM') => {
    setAmPm(newAmPm);
    emitChange(date, hasTime, hour12, minute, newAmPm, selectedTz.offset, timingQualifier);
  };

  const handleTimezoneChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newId = e.target.value;
    setTimezoneId(newId);
    const tz = TIMEZONE_OPTIONS.find(t => t.id === newId) || TIMEZONE_OPTIONS[0];
    emitChange(date, hasTime, hour12, minute, ampm, tz.offset, timingQualifier);
  };

  const handleQualifierChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newQual = e.target.value;
    setTimingQualifier(newQual);
    const newHasTime = newQual === 'DATE_ONLY' || newQual === 'UNRESOLVED' ? false : true;
    setHasTime(newHasTime);
    emitChange(date, newHasTime, hour12, minute, ampm, selectedTz.offset, newQual);
  };

  // Quick slot helpers
  const applyTimeSlot = (h: string, m: string, p: 'AM' | 'PM') => {
    setHasTime(true);
    setHour12(h);
    setMinute(m);
    setAmPm(p);
    const newQual = timingQualifier === 'DATE_ONLY' ? 'DEADLINE' : timingQualifier;
    setTimingQualifier(newQual);
    emitChange(date, true, h, m, p, selectedTz.offset, newQual);
  };

  // Suggestion actions
  const handleApplyDateOnlySuggestion = () => {
    // If evidence has normalized date, use it; otherwise preserve date
    const extractedDate = String(evidence?.normalized_value || '').slice(0, 10) || date || '2026-10-28';
    setDate(extractedDate);
    setHasTime(false);
    setTimingQualifier('DATE_ONLY');
    emitChange(extractedDate, false, hour12, minute, ampm, selectedTz.offset, 'DATE_ONLY');
  };

  const handleApplyMorningSlotSuggestion = () => {
    const extractedDate = String(evidence?.normalized_value || '').slice(0, 10) || date || '2026-10-28';
    setDate(extractedDate);
    setHasTime(true);
    setHour12('10');
    setMinute('00');
    setAmPm('AM');
    setTimingQualifier('DEADLINE');
    emitChange(extractedDate, true, '10', '00', 'AM', selectedTz.offset, 'DEADLINE');
  };

  // Human preview text
  const humanPreview = useMemo(() => {
    return formatHumanReadablePreview(
      date,
      hasTime,
      hour12,
      minute,
      ampm,
      selectedTz.code,
      selectedTz.offset,
      timingQualifier
    );
  }, [date, hasTime, hour12, minute, ampm, selectedTz, timingQualifier]);

  return (
    <div className="hr-delivery-workspace" onFocus={onFocus} data-component="RequestedDeliveryField">
      {/* Label and Evidence trigger */}
      <div className="hr-field-label">
        <label htmlFor="delivery-date-input">
          Requested delivery <span className="hr-req-star">*</span> (major field)
        </label>
        <span
          className={`hr-chip ${
            !date ? 'amber' : hasTime ? 'green' : 'blue'
          }`}
          data-testid="delivery-status-chip"
        >
          {!date ? 'Date missing' : hasTime ? 'Confirmed' : 'Date only (Time unresolved)'}
        </span>
        {onToggleEvidence && (
          <button
            type="button"
            className="hr-ev-btn"
            title="Show evidence"
            onClick={e => {
              e.stopPropagation();
              onToggleEvidence();
            }}
          >
            🔍
          </button>
        )}
      </div>

      {/* Relative / Vague Evidence Suggestion Notice */}
      {isVagueOrRelative && !dismissSuggestion && (
        <div className="hr-delivery-suggestion-box" role="region" aria-label="Delivery suggestion hint">
          <div className="hr-suggestion-top">
            <span className="hr-suggestion-badge">💡 Source hint</span>
            <span className="hr-suggestion-quote">"{evidenceQuote}"</span>
            <button
              type="button"
              className="hr-suggestion-close"
              title="Dismiss hint"
              onClick={() => setDismissSuggestion(true)}
            >
              ×
            </button>
          </div>
          <p className="hr-suggestion-text">
            Customer requested a relative or approximate time window. Under zero-guessing policy, exact delivery time
            remains unresolved until explicitly confirmed by the reviewer.
          </p>
          <div className="hr-suggestion-actions">
            <button
              type="button"
              className="hr-btn-suggestion secondary"
              onClick={handleApplyDateOnlySuggestion}
              data-testid="apply-date-only-suggestion"
            >
              Keep date only (Time unresolved)
            </button>
            <button
              type="button"
              className="hr-btn-suggestion primary"
              onClick={handleApplyMorningSlotSuggestion}
              data-testid="apply-morning-slot-suggestion"
            >
              Confirm 10:00 AM slot
            </button>
          </div>
        </div>
      )}

      {/* Main Delivery Input Grid */}
      <div className="hr-delivery-form-grid">
        {/* Date picker */}
        <div className="hr-form-col">
          <label htmlFor="delivery-date-input" className="hr-sub-label">
            Delivery date
          </label>
          <input
            type="date"
            id="delivery-date-input"
            className="hr-filter-input hr-date-picker-input"
            value={date}
            onChange={handleDateChange}
            disabled={disabled}
            aria-label="Delivery date"
          />
        </div>

        {/* Timezone picker */}
        <div className="hr-form-col">
          <label htmlFor="delivery-tz-select" className="hr-sub-label">
            Timezone <span className="hr-tz-default-note">(Default: MYT)</span>
          </label>
          <select
            id="delivery-tz-select"
            className="hr-filter-select"
            value={timezoneId}
            onChange={handleTimezoneChange}
            disabled={disabled}
            aria-label="Delivery timezone"
          >
            {TIMEZONE_OPTIONS.map(tz => (
              <option key={tz.id} value={tz.id}>
                {tz.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Time Picker and Timing Qualifier Row */}
      <div className="hr-delivery-time-row">
        {/* Time input block */}
        <div className="hr-time-block">
          <div className="hr-time-header">
            <label htmlFor="delivery-has-time-toggle" className="hr-checkbox-label">
              <input
                type="checkbox"
                id="delivery-has-time-toggle"
                checked={hasTime}
                onChange={handleToggleExactTime}
                disabled={disabled}
              />
              <span>Specify exact time</span>
            </label>
            {!hasTime && (
              <span className="hr-time-unresolved-pill">
                Time unresolved · Zero-guessing active
              </span>
            )}
          </div>

          {hasTime ? (
            <div className="hr-time-controls" data-testid="time-picker-controls">
              {/* Hour selector */}
              <select
                className="hr-time-select"
                value={hour12}
                onChange={handleHourChange}
                disabled={disabled}
                aria-label="Delivery hour"
              >
                {['01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11', '12'].map(h => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </select>

              <span className="hr-time-colon">:</span>

              {/* Minute selector */}
              <select
                className="hr-time-select"
                value={minute}
                onChange={handleMinuteChange}
                disabled={disabled}
                aria-label="Delivery minute"
              >
                {['00', '05', '10', '15', '20', '25', '30', '35', '40', '45', '50', '55'].map(m => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>

              {/* AM / PM Segmented Control */}
              <div className="hr-ampm-segment" role="group" aria-label="AM or PM">
                <button
                  type="button"
                  className={`hr-ampm-btn ${ampm === 'AM' ? 'active' : ''}`}
                  onClick={() => handleAmPmToggle('AM')}
                  disabled={disabled}
                >
                  AM
                </button>
                <button
                  type="button"
                  className={`hr-ampm-btn ${ampm === 'PM' ? 'active' : ''}`}
                  onClick={() => handleAmPmToggle('PM')}
                  disabled={disabled}
                >
                  PM
                </button>
              </div>

              {/* Quick time slots */}
              <div className="hr-quick-slots">
                <button
                  type="button"
                  className="hr-slot-pill"
                  onClick={() => applyTimeSlot('09', '00', 'AM')}
                  title="9:00 AM"
                >
                  Morning (9am)
                </button>
                <button
                  type="button"
                  className="hr-slot-pill"
                  onClick={() => applyTimeSlot('12', '00', 'PM')}
                  title="12:00 PM"
                >
                  Noon (12pm)
                </button>
                <button
                  type="button"
                  className="hr-slot-pill"
                  onClick={() => applyTimeSlot('03', '00', 'PM')}
                  title="3:00 PM"
                >
                  Afternoon (3pm)
                </button>
              </div>
            </div>
          ) : (
            <p className="hr-time-disabled-hint">
              Date only order. Clock time is left unresolved to prevent fabricating arbitrary delivery promises.
            </p>
          )}
        </div>

        {/* Qualifier selector */}
        <div className="hr-qualifier-block">
          <label htmlFor="delivery-qualifier-select" className="hr-sub-label">
            Timing qualifier
          </label>
          <select
            id="delivery-qualifier-select"
            className="hr-filter-select"
            value={timingQualifier}
            onChange={handleQualifierChange}
            disabled={disabled}
            aria-label="Timing qualifier"
          >
            {QUALIFIER_OPTIONS.map(q => (
              <option key={q.value} value={q.value}>
                {q.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Human-readable Preview Bar */}
      <div className="hr-delivery-preview-bar" data-testid="delivery-human-preview">
        <span className="hr-preview-icon" aria-hidden="true">
          🗓️
        </span>
        <span className="hr-preview-text">
          <strong>Selected delivery:</strong> {humanPreview}
        </span>
      </div>

      {/* Advanced Details Toggle (shows raw ISO and raw input for tests/power users) */}
      <details
        className="hr-delivery-advanced"
        open={isAdvancedOpen}
        onToggle={e => setIsAdvancedOpen((e.target as HTMLDetailsElement).open)}
      >
        <summary className="hr-advanced-summary">
          Advanced details &amp; ISO 8601 timestamp
        </summary>
        <div className="hr-advanced-body">
          <div className="hr-advanced-row">
            <span className="hr-advanced-label">Serialized ISO 8601:</span>
            <code className="hr-advanced-code" data-testid="serialized-iso-code">
              {serializedValue || '(null - unresolved)'}
            </code>
          </div>
          <div className="hr-advanced-row">
            <span className="hr-advanced-label">Qualifier:</span>
            <code>{timingQualifier}</code>
          </div>
          <div className="hr-advanced-row">
            <span className="hr-advanced-label">Timezone Offset:</span>
            <code>{selectedTz.offset} ({selectedTz.code})</code>
          </div>

          {/* Fallback raw input to guarantee backward compatibility with automated test suites */}
          <div style={{ marginTop: '10px' }}>
            <label htmlFor="delivery-input" className="hr-advanced-label" style={{ display: 'block', marginBottom: '4px' }}>
              Manual ISO override (power user)
            </label>
            <input
              type="text"
              id="delivery-input"
              className="hr-filter-input"
              value={serializedValue}
              onChange={e => {
                const val = e.target.value;
                onChange(val, timingQualifier);
              }}
              placeholder="2026-10-28T10:00:00+08:00"
              disabled={disabled}
            />
          </div>
        </div>
      </details>
    </div>
  );
}
