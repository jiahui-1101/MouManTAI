import { Component, type ErrorInfo, type ReactNode } from "react";

export interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  errorMessage: string | null;
}

/**
 * Shared Application Error Boundary (FE-01b).
 * Catches rendering errors, prevents application crashes,
 * provides a retry/reset affordance, and ensures no raw stack traces are exposed.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, errorMessage: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    const rawMessage = error?.message || "An unexpected rendering error occurred.";
    // Sanitize error message to prevent leaking system internals or raw stack traces
    const sanitized = rawMessage.split("\n")[0].slice(0, 200);
    return {
      hasError: true,
      errorMessage: sanitized,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log to console in development without exposing stack trace in the UI DOM
    if (typeof import.meta !== "undefined" && import.meta.env?.MODE !== "test") {
      console.error("ErrorBoundary caught an unhandled error:", error, errorInfo);
    }
  }

  handleReset = (): void => {
    this.setState({ hasError: false, errorMessage: null });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div role="alert" className="error-boundary-card notice-card" data-testid="error-boundary-fallback">
          <div className="error-boundary-header">
            <h3>Something went wrong</h3>
            <p className="muted">An unhandled view error was prevented from crashing the workspace.</p>
          </div>
          <p className="error-boundary-message" data-testid="error-boundary-message">
            {this.state.errorMessage}
          </p>
          <div className="error-boundary-actions">
            <button
              type="button"
              onClick={this.handleReset}
              className="btn btn-secondary btn-sm"
              data-testid="error-boundary-retry-button"
            >
              Retry
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
