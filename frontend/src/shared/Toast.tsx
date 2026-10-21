import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type ToastVariant = "success" | "error" | "info" | "warning";

export interface ToastItem {
  id: string;
  message: string;
  variant: ToastVariant;
  durationMs?: number;
}

export interface ToastContextValue {
  toasts: ToastItem[];
  showToast: (message: string, variant?: ToastVariant, durationMs?: number) => void;
  success: (message: string, durationMs?: number) => void;
  error: (message: string, durationMs?: number) => void;
  info: (message: string, durationMs?: number) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let toastSeq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, variant: ToastVariant = "info", durationMs: number = 4000) => {
      // Invariant: Never show a success toast for a pending or awaiting state (FE-01c)
      let resolvedVariant = variant;
      if (variant === "success" && /pending|awaiting/i.test(message)) {
        resolvedVariant = "info";
      }

      const id = `toast_${Date.now()}_${++toastSeq}`;
      const item: ToastItem = { id, message, variant: resolvedVariant, durationMs };

      setToasts((prev) => [...prev, item]);

      if (durationMs > 0) {
        setTimeout(() => {
          removeToast(id);
        }, durationMs);
      }
    },
    [removeToast],
  );

  const success = useCallback(
    (message: string, durationMs?: number) => showToast(message, "success", durationMs),
    [showToast],
  );

  const error = useCallback(
    (message: string, durationMs?: number) => showToast(message, "error", durationMs),
    [showToast],
  );

  const info = useCallback(
    (message: string, durationMs?: number) => showToast(message, "info", durationMs),
    [showToast],
  );

  const value = useMemo(
    () => ({
      toasts,
      showToast,
      success,
      error,
      info,
      removeToast,
    }),
    [toasts, showToast, success, error, info, removeToast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="toast-container"
        role="region"
        aria-label="Notifications"
        data-testid="toast-container"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.variant === "error" ? "alert" : "status"}
            className={`toast-item toast-${t.variant}`}
            data-testid={`toast-${t.variant}`}
          >
            <span className="toast-icon">
              {t.variant === "success" ? "✅" : t.variant === "error" ? "❌" : t.variant === "warning" ? "⚠️" : "ℹ️"}
            </span>
            <span className="toast-message">{t.message}</span>
            <button
              type="button"
              className="toast-close"
              onClick={() => removeToast(t.id)}
              aria-label="Dismiss notification"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Return a safe no-op object if used outside ToastProvider
    return {
      toasts: [],
      showToast: () => {},
      success: () => {},
      error: () => {},
      info: () => {},
      removeToast: () => {},
    };
  }
  return ctx;
}
