/** Three small drawings for the "how it works" cards. SVG and CSS only; motion is in landing.css. */

const READINGS = [
  "yes",
  "no",
  "yes",
  "unknown",
  "yes",
  "yes",
  "no",
  "yes",
  "unknown",
  "no",
] as const;

/** One screen, the whole story: sheets of evidence stacked over a map. */
export function GatherVignette() {
  return (
    <svg
      viewBox="0 0 240 160"
      className="vig"
      role="img"
      aria-label="Sheets of evidence stacked over a map"
    >
      <g className="vig-float vig-float-3">
        <rect
          x="42"
          y="30"
          width="156"
          height="104"
          rx="14"
          className="fill-surface-2 stroke-line"
        />
      </g>
      <g className="vig-float vig-float-2">
        <rect x="30" y="22" width="156" height="104" rx="14" className="fill-surface stroke-line" />
        <rect x="46" y="40" width="72" height="8" rx="4" className="fill-ink-2" opacity="0.35" />
        <rect x="46" y="56" width="108" height="8" rx="4" className="fill-ink-2" opacity="0.2" />
        <rect x="46" y="72" width="90" height="8" rx="4" className="fill-ink-2" opacity="0.2" />
      </g>
      <g className="vig-float">
        <rect x="58" y="46" width="156" height="104" rx="14" className="fill-surface stroke-line" />
        <path
          d="M58 118 C 90 96 120 128 150 108 S 196 98 214 110 L 214 136 a14 14 0 0 1 -14 14 L 72 150 a14 14 0 0 1 -14 -14 Z"
          fill="var(--map-water)"
        />
        <path d="M70 64 L 130 64 L 130 92 L 70 92 Z" fill="var(--map-park)" />
        <rect x="142" y="62" width="22" height="16" rx="3" fill="var(--map-building)" />
        <rect x="170" y="62" width="30" height="16" rx="3" fill="var(--map-building)" />
        <rect x="142" y="84" width="40" height="14" rx="3" fill="var(--map-building)" />
        <rect
          x="138"
          y="58"
          width="68"
          height="46"
          rx="8"
          fill="none"
          stroke="var(--map-flag)"
          strokeWidth="2"
          strokeDasharray="6 4"
        />
        <circle cx="206" cy="58" r="6" className="fill-accent" />
      </g>
    </svg>
  );
}

/** Ten questions, every answer shown: a grid of readings that lights up one by one. */
export function AskVignette() {
  return (
    <svg
      viewBox="0 0 240 160"
      className="vig"
      role="img"
      aria-label="Ten answers laid out in two rows: yes, no or unknown"
    >
      <rect x="14" y="16" width="212" height="128" rx="16" className="fill-surface stroke-line" />
      {READINGS.map((reading, index) => {
        const col = index % 5;
        const row = Math.floor(index / 5);
        const cx = 44 + col * 38;
        const cy = 56 + row * 52;
        return (
          <g key={index} className="vig-dot" style={{ ["--i" as string]: index }}>
            {reading === "yes" ? (
              <>
                <circle cx={cx} cy={cy} r="14" className="fill-accent" />
                <path
                  d={`M${cx - 6} ${cy} l4.5 4.5 l8 -9`}
                  fill="none"
                  strokeWidth="2.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="stroke-accent-fg"
                />
              </>
            ) : null}
            {reading === "no" ? (
              <>
                <circle
                  cx={cx}
                  cy={cy}
                  r="13"
                  className="fill-surface-2 stroke-ink-2"
                  strokeWidth="1.8"
                />
                <path
                  d={`M${cx - 5} ${cy - 5} l10 10 M${cx + 5} ${cy - 5} l-10 10`}
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  className="stroke-ink-2"
                />
              </>
            ) : null}
            {reading === "unknown" ? (
              <>
                <circle
                  cx={cx}
                  cy={cy}
                  r="13"
                  fill="none"
                  strokeWidth="1.8"
                  strokeDasharray="4 3"
                  className="stroke-ink-2"
                />
                <circle cx={cx} cy={cy} r="2" className="fill-ink-2" />
              </>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

/** You write, you post: a drafted comment with a copy button and a tick. */
export function DecideVignette() {
  return (
    <svg
      viewBox="0 0 240 160"
      className="vig"
      role="img"
      aria-label="A drafted comment with a copy button; a person posts it"
    >
      <rect x="18" y="18" width="204" height="124" rx="16" className="fill-surface stroke-line" />
      <circle cx="42" cy="42" r="9" className="fill-accent" opacity="0.9" />
      <rect x="58" y="36" width="64" height="8" rx="4" className="fill-ink-2" opacity="0.4" />
      <rect x="34" y="62" width="168" height="8" rx="4" className="fill-ink-2" opacity="0.28" />
      <rect x="34" y="78" width="150" height="8" rx="4" className="fill-ink-2" opacity="0.28" />
      <rect x="34" y="94" width="76" height="8" rx="4" className="fill-ink-2" opacity="0.28" />
      <rect x="114" y="92" width="3" height="12" rx="1.5" className="fill-accent vig-caret" />
      <rect x="34" y="112" width="68" height="20" rx="10" className="fill-accent" />
      <rect x="46" y="120" width="44" height="4" rx="2" className="fill-accent-fg" opacity="0.9" />
      <g className="vig-float">
        <circle cx="196" cy="122" r="14" className="fill-surface-2 stroke-line" />
        <path
          d="M189 122 l5 5 l9 -10"
          fill="none"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="stroke-accent"
        />
      </g>
    </svg>
  );
}
