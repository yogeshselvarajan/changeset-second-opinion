import "../landing.css";
import { usePointerParallax } from "../motion";
import {
  CALLOUTS,
  FLAG,
  MAJOR_ROADS,
  MINOR_ROADS,
  PARKS,
  RIVER,
  VIEW,
  buildBlocks,
  type Block,
} from "./mapData";

const TONE_LABEL = { flag: "Worth a look", info: "Evidence", ok: "Decision" } as const;
/** Card size as a share of the picture's width, and its height in drawing units (see landing.css). */
const CARD_W = 0.29;
const CARD_H = 78;
/** The town is the same on every render (seeded), so it is built once. */
const BLOCKS = buildBlocks();

function center(block: Block) {
  return { x: block.x + block.w / 2, y: block.y + block.h / 2 };
}

/**
 * The hero picture: a made-up town drawn like a street map, with a pretend flagged edit on it.
 * On load the streets draw themselves, the edited buildings light up and small cards attach to the
 * evidence; the pointer moves the layers a few pixels at different depths. Everything is SVG and
 * CSS, so it prerenders to static HTML, follows light and dark, and stands still when the visitor
 * asks for less motion. It is an illustration, not map data.
 */
export function LivingMap({
  variant = "hero",
  label = "An illustrated street map. One group of buildings is outlined as a flagged edit; small cards point to the evidence a reviewer sees.",
}: {
  variant?: "hero" | "compact";
  label?: string;
}) {
  const blocks = BLOCKS;
  const stage = usePointerParallax<HTMLDivElement>();
  const deleted = blocks.find((block) => block.kind === "deleted");
  const callouts = CALLOUTS.map((callout) =>
    callout.id === "deleted" && deleted ? { ...callout, to: center(deleted) } : callout,
  );

  return (
    <figure className="living-map" data-variant={variant} aria-label={label}>
      <div ref={stage} className="lm-stage">
        <svg
          viewBox={`0 0 ${VIEW.w} ${VIEW.h}`}
          className="lm-svg"
          role="presentation"
          focusable="false"
          preserveAspectRatio="xMidYMid meet"
        >
          <rect width={VIEW.w} height={VIEW.h} className="lm-land" />

          <g className="lm-depth-1">
            <g className="lm-blocks">
              {blocks.map((block) =>
                block.kind === "plain" ? (
                  <rect
                    key={`${block.x}-${block.y}`}
                    x={block.x}
                    y={block.y}
                    width={block.w}
                    height={block.h}
                    rx="2"
                    className="lm-building"
                  />
                ) : null,
              )}
            </g>

            {MINOR_ROADS.map((d, index) => (
              <path
                key={d}
                d={d}
                pathLength={1}
                className="lm-street lm-draw"
                style={{ animationDelay: `${0.05 * index}s` }}
              />
            ))}

            {PARKS.map((d, index) => (
              <path
                key={d}
                d={d}
                className="lm-park"
                style={{ animationDelay: `${0.5 + 0.12 * index}s` }}
              />
            ))}

            <path d={RIVER} className="lm-river-bed" />
            <path
              d={RIVER}
              pathLength={1}
              className="lm-river lm-draw"
              style={{ animationDelay: "0.3s", animationDuration: "1.9s" }}
            />

            {MAJOR_ROADS.map((d, index) => (
              <g key={d}>
                <path d={d} className="lm-avenue-casing" />
                <path
                  d={d}
                  pathLength={1}
                  className="lm-avenue lm-draw"
                  style={{ animationDelay: `${0.2 + 0.18 * index}s`, animationDuration: "1.7s" }}
                />
              </g>
            ))}
          </g>

          <g className="lm-depth-2">
            <rect
              x={FLAG.x - 10}
              y={FLAG.y - 10}
              width={FLAG.w + 20}
              height={FLAG.h + 20}
              rx="16"
              className="lm-flag-wash"
            />
            {blocks.map((block) =>
              block.kind === "plain" ? null : (
                <rect
                  key={`${block.x}-${block.y}`}
                  x={block.x}
                  y={block.y}
                  width={block.w}
                  height={block.h}
                  rx="2"
                  className={`lm-edit lm-edit-${block.kind}`}
                  style={{ animationDelay: `${1.5 + (block.x % 7) * 0.05}s` }}
                />
              ),
            )}
            <rect
              x={FLAG.x}
              y={FLAG.y}
              width={FLAG.w}
              height={FLAG.h}
              rx="12"
              className="lm-flag"
            />
            {callouts.map((callout) => {
              // The card is CARD_W wide and about CARD_H tall (in drawing units); the line leaves
              // from the middle of its lower or upper edge, whichever faces the target.
              const x1 = (callout.at.x + CARD_W / 2) * VIEW.w;
              const top = callout.at.y * VIEW.h;
              const y1 = callout.to.y > top + CARD_H / 2 ? top + CARD_H : top;
              return (
                <line
                  key={callout.id}
                  x1={x1}
                  y1={y1}
                  x2={callout.to.x}
                  y2={callout.to.y}
                  pathLength={1}
                  className="lm-leader lm-draw"
                  style={{ animationDelay: `${callout.delay - 0.4}s`, animationDuration: "0.7s" }}
                />
              );
            })}
            {callouts.map((callout) => (
              <circle
                key={callout.id}
                cx={callout.to.x}
                cy={callout.to.y}
                r="5"
                className="lm-pin"
                style={{ animationDelay: `${callout.delay - 0.1}s` }}
              />
            ))}
          </g>
        </svg>

        <ul className="lm-callouts">
          {callouts.map((callout) => (
            <li
              key={callout.id}
              className="lm-callout"
              data-tone={callout.tone}
              style={{
                left: `${callout.at.x * 100}%`,
                top: `${callout.at.y * 100}%`,
                animationDelay: `${callout.delay}s`,
              }}
            >
              <span className="lm-callout-tag">{TONE_LABEL[callout.tone]}</span>
              <strong className="lm-callout-title">{callout.title}</strong>
              <span className="lm-callout-detail">{callout.detail}</span>
            </li>
          ))}
        </ul>
      </div>
      <figcaption className="sr-only">
        An illustration with invented data, drawn to show how the evidence for a flagged edit sits
        on the map.
      </figcaption>
    </figure>
  );
}
