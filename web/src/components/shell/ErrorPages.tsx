import { Link } from "@tanstack/react-router";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { t } from "../../i18n";

function Page({ title, body, children }: { title: string; body: string; children?: ReactNode }) {
  return (
    <section aria-labelledby="page-title" className="mx-auto max-w-xl p-6">
      <h1 id="page-title" className="text-xl font-semibold">
        {title}
      </h1>
      <p className="mt-2 text-text-muted">{body}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function NotFoundPage() {
  return (
    <Page title={t("error.notFound.title")} body={t("error.notFound.body")}>
      <Link to="/queue" className="underline">
        {t("error.backToQueue")}
      </Link>
    </Page>
  );
}

export function ForbiddenPage() {
  return (
    <Page title={t("error.forbidden.title")} body={t("error.forbidden.body")}>
      <Link to="/queue" className="underline">
        {t("error.backToQueue")}
      </Link>
    </Page>
  );
}

interface BoundaryState {
  failed: boolean;
}

/** Last-resort fallback so a render error never leaves a blank page. */
export class ErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { failed: false };

  static getDerivedStateFromError(): BoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Message only: component stacks can carry user-entered text, so nothing else is logged.
    console.error("render error:", error.message, info.componentStack ? "(stack omitted)" : "");
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <Page title={t("error.boundary.title")} body={t("error.boundary.body")}>
        <button
          type="button"
          className="min-h-8 rounded border border-border bg-surface px-3"
          onClick={() => window.location.reload()}
        >
          {t("error.boundary.reload")}
        </button>
      </Page>
    );
  }
}
