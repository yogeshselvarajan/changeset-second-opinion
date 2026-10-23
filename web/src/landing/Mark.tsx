/** The three-bar mark (key, before, after), drawn with the theme tokens so it follows dark mode. */
export function Mark({ className = "h-5 w-auto" }: { className?: string }) {
  return (
    <svg viewBox="4 6 24 21" aria-hidden="true" focusable="false" className={className}>
      <rect className="fill-accent" x="4" y="6" width="12" height="5" rx="2.5" />
      <rect className="fill-ink" x="4" y="14" width="24" height="5" rx="2.5" />
      <rect className="fill-ink" x="4" y="22" width="18" height="5" rx="2.5" />
    </svg>
  );
}
