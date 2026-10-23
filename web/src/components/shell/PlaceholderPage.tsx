import type { ReactNode } from "react";

/** A titled placeholder that later work packages replace with the real screen. */
export function PlaceholderPage({
  title,
  body,
  children,
}: {
  title: string;
  body: string;
  children?: ReactNode;
}) {
  return (
    <section aria-labelledby="page-title" className="p-4">
      <h1 id="page-title" className="text-xl font-semibold">
        {title}
      </h1>
      <p className="mt-2 text-text-muted">{body}</p>
      {children}
    </section>
  );
}
