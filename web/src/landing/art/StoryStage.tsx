import type { ReactNode } from "react";

import { FLAG, MAJOR_ROADS, MINOR_ROADS, PARKS, RIVER, buildBlocks, type Block } from "./mapData";

/**
 * The pinned story on wide screens: one patch of map that a flagged edit is read on. Desktop only,
 * drawn by the lazy motion chunk (src/motion/landing.ts); without it the block stays hidden and the
 * three cards beneath it carry the same content in words. It is decoration (aria-hidden), an
 * illustration with invented geometry and readings copied from a real run.
 */
export const STORY_VIEW = { w: 960, h: 600 } as const;

/** The ten readings of a real run (changeset 188909786, 20 October 2026), in the panel's order. */
export const STORY_READINGS = [
  0.5238, 0.1497, 0.4771, 0.4834, 0.1011, 0.2506, 0.2035, 0.1085, 0.1709, 0.3357,
] as const;

export const STORY_CHANGESET = 188909786;

const STRIPS = [
  { label: "Account", value: "3 days old" },
  { label: "Comment", value: "fix names" },
  { label: "Deleted", value: "a library" },
  { label: "Tag changed", value: "name" },
  { label: "Discussion", value: "none yet" },
] as const;

const BLOCKS = buildBlocks();

function ring(index: number) {
  const col = index % 5;
  const row = Math.floor(index / 5);
  return { x: 86 + col * 78, y: 470 + row * 74 };
}

function stateOf(p: number): "yes" | "no" | "unknown" {
  if (p > 0.65) return "yes";
  if (p < 0.35) return "no";
  return "unknown";
}

export function StoryStage({
  scenes,
  footnote,
}: {
  scenes: readonly { tag: string; title: string; body: string }[];
  footnote: ReactNode;
}) {
  const plain = BLOCKS.filter((block: Block) => block.kind === "plain");
  const edits = BLOCKS.filter((block: Block) => block.kind !== "plain");
  return (
    <div className="story" data-story>
      <div className="story-stage" aria-hidden="true">
        <svg
          viewBox={`0 0 ${STORY_VIEW.w} ${STORY_VIEW.h}`}
          className="story-svg"
          role="presentation"
          focusable="false"
          preserveAspectRatio="xMidYMid meet"
        >
          <rect width={STORY_VIEW.w} height={STORY_VIEW.h} className="lm-land" />
          <g className="st-map">
            {plain.map((block) => (
              <rect
                key={`${block.x}-${block.y}`}
                x={block.x}
                y={block.y}
                width={block.w}
                height={block.h}
                rx="2"
                className="lm-building"
              />
            ))}
            {MINOR_ROADS.map((d) => (
              <path key={d} d={d} className="lm-street" />
            ))}
            {PARKS.map((d) => (
              <path key={d} d={d} className="lm-park st-static" />
            ))}
            <path d={RIVER} className="lm-river-bed st-static" />
            <path id="st-river" d={RIVER} className="lm-river" />
            {MAJOR_ROADS.map((d) => (
              <g key={d}>
                <path d={d} className="lm-avenue-casing st-static" />
                <path d={d} className="lm-avenue" />
              </g>
            ))}
          </g>

          <g className="st-flagged">
            <rect
              x={FLAG.x}
              y={FLAG.y}
              width={FLAG.w}
              height={FLAG.h}
              rx="12"
              className="st-bbox"
            />
            {edits.map((block) => (
              <rect
                key={`${block.x}-${block.y}`}
                x={block.x}
                y={block.y}
                width={block.w}
                height={block.h}
                rx="2"
                className={`st-edit lm-edit-${block.kind}`}
                data-kind={block.kind}
              />
            ))}
          </g>

          <g className="st-strips">
            {STRIPS.map((strip, index) => (
              <g key={strip.label} className="st-strip" data-index={index}>
                <rect x="0" y="0" width="236" height="40" rx="10" className="st-card" />
                <rect x="12" y="13" width="14" height="5" rx="2.5" className="st-key" />
                <rect x="12" y="22" width="22" height="5" rx="2.5" className="st-bar" />
                <text x="46" y="17" className="st-label">
                  {strip.label}
                </text>
                <text x="46" y="32" className="st-value">
                  {strip.value}
                </text>
              </g>
            ))}
          </g>

          <g className="st-rings">
            <rect x="44" y="428" width="380" height="156" rx="18" className="st-card st-ringbox" />
            {STORY_READINGS.map((p, index) => {
              const { x, y } = ring(index);
              const state = stateOf(p);
              return (
                <g key={index} className="st-ring" data-state={state} data-p={p}>
                  <circle cx={x} cy={y} r="24" className="st-track" />
                  <circle
                    cx={x}
                    cy={y}
                    r="24"
                    className="st-fill"
                    transform={`rotate(-90 ${x} ${y})`}
                  />
                  <text x={x} y={y + 4} textAnchor="middle" className="st-num">
                    {index + 1}
                  </text>
                </g>
              );
            })}
          </g>

          <g className="st-draft">
            <rect x="540" y="430" width="380" height="140" rx="16" className="st-card" />
            <text x="562" y="458" className="st-label">
              Draft comment
            </text>
            <g className="st-draft-lines">
              <text x="562" y="488" className="st-value">
                Thank you for mapping near the park.
              </text>
              <text x="562" y="510" className="st-value">
                Could you tell us where the library
              </text>
              <text x="562" y="532" className="st-value">
                information came from?
              </text>
            </g>
            <rect x="562" y="546" width="86" height="12" rx="6" className="st-bar" />
          </g>

          <circle className="st-mapper" r="9" cx="0" cy="0" />
        </svg>

        <ol className="story-scenes">
          {scenes.map((scene, index) => (
            <li key={scene.tag} className="story-scene" data-index={index}>
              <span className="eyebrow">{scene.tag}</span>
              <strong className="display">{scene.title}</strong>
              <span>{scene.body}</span>
            </li>
          ))}
        </ol>
      </div>
      <p className="story-foot">{footnote}</p>
    </div>
  );
}
