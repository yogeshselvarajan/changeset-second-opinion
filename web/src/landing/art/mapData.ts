/**
 * The drawing behind the hero: a made-up town in the style of an OpenStreetMap carto sheet.
 *
 * Nothing here is real map data. Buildings come from a seeded generator, so the static HTML and the
 * first browser render are identical, and the picture never depends on a tile server or a licence.
 * Roads, the river and the parks are drawn over the buildings, so a block that falls under one is
 * simply hidden and no geometry test is needed.
 */

export const VIEW = { w: 960, h: 640 } as const;

/** The area a pretend flagged changeset covers. */
export const FLAG = { x: 372, y: 190, w: 276, h: 182 } as const;

export type BlockKind = "plain" | "added" | "changed" | "deleted";

export interface Block {
  x: number;
  y: number;
  w: number;
  h: number;
  kind: BlockKind;
}

/** Small, fast, seedable generator (mulberry32). */
function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const round = (value: number) => Math.round(value * 10) / 10;

function inside(block: Block): boolean {
  const cx = block.x + block.w / 2;
  const cy = block.y + block.h / 2;
  return cx > FLAG.x && cx < FLAG.x + FLAG.w && cy > FLAG.y && cy < FLAG.y + FLAG.h;
}

/** Which of the blocks inside the flagged area are drawn as edits, by position in that area. */
const ADDED = new Set([1, 4, 7, 10, 13]);
const CHANGED = new Set([2, 8, 11]);
const DELETED = new Set([5]);

export function buildBlocks(): Block[] {
  const next = seeded(20261019);
  const blocks: Block[] = [];
  for (let row = 0; row < 18; row++) {
    for (let col = 0; col < 23; col++) {
      if (next() < 0.26) continue;
      const w = 20 + next() * 16;
      const h = 16 + next() * 14;
      blocks.push({
        x: round(-14 + col * 44 + next() * 8),
        y: round(-10 + row * 36 + next() * 6),
        w: round(w),
        h: round(h),
        kind: "plain",
      });
    }
  }
  let seen = 0;
  for (const block of blocks) {
    if (!inside(block)) continue;
    if (ADDED.has(seen)) block.kind = "added";
    else if (CHANGED.has(seen)) block.kind = "changed";
    else if (DELETED.has(seen)) block.kind = "deleted";
    seen += 1;
  }
  return blocks;
}

export const RIVER = "M -30 452 C 120 404 250 486 410 452 S 690 392 990 486";

export const PARKS = [
  "M 548 70 C 600 24 700 30 742 78 C 780 124 736 176 668 180 C 596 184 520 130 548 70 Z",
  "M 62 520 C 110 480 214 490 246 540 C 270 584 212 624 140 618 C 70 612 28 566 62 520 Z",
  "M 800 330 C 850 304 920 320 936 366 C 946 402 900 428 852 420 C 800 410 770 360 800 330 Z",
] as const;

/** Avenues: wide, drawn with a casing. */
export const MAJOR_ROADS = [
  "M -30 262 C 190 236 372 306 556 268 S 862 214 990 246",
  "M 296 -30 C 330 150 276 300 338 462 S 424 640 436 680",
  "M 706 -30 C 694 124 764 222 742 332 S 702 510 764 680",
  "M -30 574 C 160 548 304 570 466 546 S 768 528 990 566",
] as const;

/** Streets: thin lines on a loose grid. */
export const MINOR_ROADS: readonly string[] = (() => {
  const next = seeded(7);
  const lines: string[] = [];
  for (let k = 0; k < 8; k++) {
    const y = round(34 + k * 82 + next() * 10);
    lines.push(`M -20 ${y} L 980 ${round(y + (next() - 0.5) * 36)}`);
  }
  for (let k = 0; k < 10; k++) {
    const x = round(30 + k * 100 + next() * 14);
    lines.push(`M ${x} -20 L ${round(x + (next() - 0.5) * 40)} 660`);
  }
  return lines;
})();

export interface Callout {
  id: string;
  tone: "flag" | "info" | "ok";
  title: string;
  detail: string;
  /** Position of the card as a share of the picture. */
  at: { x: number; y: number };
  /** Where its line lands on the map, in drawing units. */
  to: { x: number; y: number };
  /** Seconds after load. */
  delay: number;
}

export const CALLOUTS: readonly Callout[] = [
  {
    id: "deleted",
    tone: "flag",
    title: "A library, gone",
    detail: "Mapped for 6 years",
    at: { x: 0.04, y: 0.06 },
    to: { x: 478, y: 270 },
    delay: 2.1,
  },
  {
    id: "account",
    tone: "info",
    title: "A brand new account",
    detail: "Joined 3 days ago",
    at: { x: 0.69, y: 0.04 },
    to: { x: 600, y: 214 },
    delay: 2.5,
  },
  {
    id: "comment",
    tone: "info",
    title: "“fix names”",
    detail: "The comment, next to the changes",
    at: { x: 0.64, y: 0.66 },
    to: { x: 612, y: 346 },
    delay: 2.9,
  },
  {
    id: "decision",
    tone: "ok",
    title: "Your call",
    detail: "A person decides and posts",
    at: { x: 0.05, y: 0.74 },
    to: { x: 392, y: 352 },
    delay: 3.4,
  },
];
