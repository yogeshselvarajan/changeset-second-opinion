import type { ReactNode } from "react";

/**
 * A labelled region of the case screen. `j` and `k` move between these, so each one can take focus
 * (tabIndex -1) without being a tab stop.
 */
export function Section({
  id,
  title,
  children,
  actions,
  testId,
}: {
  id: string;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  testId?: string;
}) {
  const headingId = `${id}-heading`;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      data-case-section={id}
      data-testid={testId ?? id}
      tabIndex={-1}
      className="cso-card mt-4 first:mt-0"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="cso-card-title m-0 text-base font-semibold">
          {title}
        </h3>
        {actions}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** A label and its value in a definition list row. */
export function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-x-3 sm:grid-cols-[10rem_1fr]">
      <dt className="text-sm text-text-muted">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

/** A busy placeholder for one section while its data loads. */
export function SectionSkeleton({ label }: { label: string }) {
  return (
    <div aria-busy="true" role="status" className="space-y-2">
      <span className="sr-only">{label}</span>
      <div className="h-4 w-3/4 rounded bg-border" aria-hidden="true" />
      <div className="h-4 w-1/2 rounded bg-border" aria-hidden="true" />
    </div>
  );
}
