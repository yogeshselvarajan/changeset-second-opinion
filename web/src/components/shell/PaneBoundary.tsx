import { Component, type ErrorInfo, type ReactNode } from "react";

import { t } from "../../i18n";

interface State {
  failed: boolean;
}

/**
 * Keeps one failing pane from taking the screen with it: if the evidence pane or the verdict pane
 * throws while rendering, the other stays usable and this one says so in a sentence, with a button
 * that tries to draw it again. `name` is only used in the log line.
 */
export class PaneBoundary extends Component<{ name: string; children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Message only: component stacks can carry user-entered text, so nothing else is logged.
    console.error(
      `pane error (${this.props.name}):`,
      error.message,
      info.componentStack ? "(stack omitted)" : "",
    );
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" data-testid={`pane-failed-${this.props.name}`} className="p-4">
        <p className="m-0">{t("pane.failed")}</p>
        <button
          type="button"
          className="mt-3 min-h-8 rounded-[var(--radius-control)] border border-control-border bg-surface px-3 text-ink"
          onClick={() => this.setState({ failed: false })}
        >
          {t("pane.reload")}
        </button>
      </div>
    );
  }
}
