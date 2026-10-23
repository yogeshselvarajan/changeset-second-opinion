/* eslint-disable jsx-a11y/no-noninteractive-tabindex -- a scrollable region must be focusable (WCAG 2.1.1) */
import type { ReactNode } from "react";

/**
 * A wide table that scrolls sideways on a narrow screen. A scrollable area has to take keyboard
 * focus, or a keyboard user cannot scroll it (WCAG 2.1.1; axe: scrollable-region-focusable), so it
 * is focusable and labelled even though it is not a control.
 */
export function ScrollRegion({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="region"
      tabIndex={0}
      aria-label={label}
      className={`relative overflow-x-auto ${className ?? ""}`}
    >
      {children}
    </div>
  );
}
