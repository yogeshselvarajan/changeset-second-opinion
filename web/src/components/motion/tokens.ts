import type { Transition } from "motion/react";

/** Motion values of the app. Durations are in seconds. */
export const motionTokens = {
  ease: {
    enter: [0.2, 0, 0, 1] as const,
    standard: [0.4, 0, 0.2, 1] as const,
  },
  duration: { fast: 0.12, standard: 0.22 },
  blur: { subtle: 2, soft: 4 },
  spring: {
    smooth: { type: "spring", stiffness: 320, damping: 36 } as Transition,
    snappy: { type: "spring", stiffness: 500, damping: 40 } as Transition,
  },
} as const;

/** Cubic-bezier arrays as the mutable tuple the animation library expects. */
export const easeEnter: [number, number, number, number] = [...motionTokens.ease.enter];
export const easeStandard: [number, number, number, number] = [...motionTokens.ease.standard];
