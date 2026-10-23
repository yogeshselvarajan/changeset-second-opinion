import { AnimatePresence, motion } from "motion/react";

import { easeEnter, easeStandard, motionTokens } from "./tokens";

/**
 * Text that rises into place when its value changes. Visual only: the caller supplies the
 * accessible text, so this renders `aria-hidden`. With reduced motion it only fades.
 */
export function RiseText({
  text,
  reduced,
  direction = 1,
}: {
  text: string;
  reduced: boolean;
  direction?: number;
}) {
  return (
    <span className="relative inline-grid overflow-hidden" aria-hidden="true">
      <AnimatePresence mode="popLayout" initial={false} custom={direction}>
        <motion.span
          key={text}
          className="col-start-1 row-start-1"
          custom={direction}
          variants={{
            from: (dir: number) =>
              reduced
                ? { opacity: 0 }
                : {
                    opacity: 0,
                    y: `${0.3 * dir}em`,
                    filter: `blur(${motionTokens.blur.soft}px)`,
                  },
            to: { opacity: 1, y: "0em", filter: "blur(0px)" },
            gone: (dir: number) =>
              reduced
                ? { opacity: 0, transition: { duration: 0 } }
                : {
                    opacity: 0,
                    y: `${-0.3 * dir}em`,
                    filter: `blur(${motionTokens.blur.subtle}px)`,
                    transition: { duration: 0.14, ease: easeStandard },
                  },
          }}
          initial="from"
          animate="to"
          exit="gone"
          transition={{
            duration: reduced ? 0.15 : motionTokens.duration.standard,
            ease: easeEnter,
          }}
        >
          {text}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}
