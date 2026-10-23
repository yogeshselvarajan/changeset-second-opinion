import { useState } from "react";

import { RiseText } from "./RiseText";
import { useReducedMotionSafe } from "./useReducedMotionSafe";

/**
 * A number whose digits roll when it changes (up when it grew, down when it shrank).
 * Under reduced motion it is plain text with no animation at all. The rolling form is one image
 * whose accessible name is the number, so a screen reader hears it once.
 */
export function RollingCount({ value }: { value: number }) {
  const reduced = useReducedMotionSafe();
  const [state, setState] = useState({ value, direction: 1 });
  if (state.value !== value) setState({ value, direction: value > state.value ? 1 : -1 });

  if (reduced) return <span className="tabular-nums">{value}</span>;

  const chars = [...String(value)];
  return (
    <span
      role="img"
      aria-label={String(value)}
      data-testid="rolling-count"
      className="inline-flex tabular-nums"
    >
      {chars.map((char, index) => (
        <span key={chars.length - index}>
          <RiseText text={char} reduced={false} direction={state.direction} />
        </span>
      ))}
    </span>
  );
}
