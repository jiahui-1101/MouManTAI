import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export interface ConfirmationDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  scope?: ReactNode;
  consequence?: ReactNode;
  requiredAcknowledgement?: string;
  pending?: boolean;
  confirmDisabled?: boolean;
  children?: ReactNode;
  onConfirm: () => void | Promise<void>;
  onConfirmError?: (error: unknown) => void;
  onOpenChange: (open: boolean) => void;
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function ConfirmationDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  scope,
  consequence,
  requiredAcknowledgement,
  pending = false,
  confirmDisabled = false,
  children,
  onConfirm,
  onConfirmError,
  onOpenChange,
}: ConfirmationDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);
  const submitting = useRef(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [submittingState, setSubmittingState] = useState(false);
  const [confirmationError, setConfirmationError] = useState(false);
  const isBusy = pending || submittingState;

  useEffect(() => {
    if (!open) return;
    setAcknowledged(false);
    setConfirmationError(false);
    previousFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusTarget = dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE) ?? dialogRef.current;
    focusTarget?.focus();
    const keepFocusInside = (event: FocusEvent) => {
      const dialog = dialogRef.current;
      if (dialog && event.target instanceof Node && !dialog.contains(event.target)) {
        (dialog.querySelector<HTMLElement>(FOCUSABLE) ?? dialog).focus();
      }
    };
    document.addEventListener("focusin", keepFocusInside);
    return () => {
      document.removeEventListener("focusin", keepFocusInside);
      previousFocus.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      if (!isBusy) onOpenChange(false);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const confirm = async () => {
    if (isBusy || confirmationError || submitting.current || (requiredAcknowledgement && !acknowledged) || confirmDisabled) return;
    submitting.current = true;
    setSubmittingState(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } catch (error) {
      setConfirmationError(true);
      onConfirmError?.(error);
    } finally {
      submitting.current = false;
      setSubmittingState(false);
    }
  };

  return (
    <div className="foundation-dialog-backdrop">
      <div
        ref={dialogRef}
        className="foundation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{description}</p>
        {scope && <div className="foundation-dialog-scope"><h3>Scope</h3>{scope}</div>}
        {consequence && <div className="foundation-dialog-consequence"><h3>Consequences</h3>{consequence}</div>}
        {children}
        {requiredAcknowledgement && (
          <label className="foundation-acknowledgement">
            <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} disabled={isBusy} />
            <span>{requiredAcknowledgement}</span>
          </label>
        )}
        {confirmationError && (
          <p className="foundation-dialog-error" role="alert">
            The action was not confirmed. Check the current record and its status before trying another action.
          </p>
        )}
        <div className="foundation-dialog-actions">
          <button type="button" className="foundation-button foundation-button-secondary" onClick={() => onOpenChange(false)} disabled={isBusy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className="foundation-button foundation-button-primary"
            onClick={() => void confirm()}
            disabled={isBusy || confirmationError || (!!requiredAcknowledgement && !acknowledged) || confirmDisabled}
          >
            {isBusy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
