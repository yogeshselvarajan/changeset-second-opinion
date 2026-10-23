import { gsap, ScrollTrigger, SplitText } from "./gsap";
import { LESS_MOTION_EVENT, readLessMotion, restoreLessMotion } from "./less";

/**
 * Motion for the home page, in the order of the page. The page is
 * complete without any of this: the static HTML is the end state, and this module only plays the way
 * there as the reader scrolls. Rules it keeps:
 *  - only transform, opacity, stroke-dashoffset and clip-path move;
 *  - motion answers the scroll, not the clock (nothing loops except the closing band drift);
 *  - a bar always fills to a probability with a visible remainder, never to 100 percent;
 *  - under prefers-reduced-motion, or the footer "Less motion" switch, no trigger is created at all.
 */

function all<T extends Element = HTMLElement>(root: ParentNode, selector: string): T[] {
  return Array.from(root.querySelectorAll<T>(selector));
}

function inView(el: Element, share = 0.88): boolean {
  return el.getBoundingClientRect().top < window.innerHeight * share;
}

function revealsAndHeadings(root: HTMLElement) {
  // Blocks fade up once as they enter; a block that already holds a split headline only fades,
  // because the lines of the headline do the travelling.
  for (const el of all(root, ".reveal")) {
    if (inView(el)) continue;
    const hasSplit = el.querySelector("[data-split]") !== null;
    const delay = (parseFloat(getComputedStyle(el).getPropertyValue("--reveal-delay")) || 0) / 1000;
    gsap.fromTo(
      el,
      { opacity: 0, y: hasSplit ? 0 : 18 },
      {
        opacity: 1,
        y: 0,
        duration: 0.4,
        delay,
        ease: "power2.out",
        clearProps: "transform,opacity",
        scrollTrigger: { trigger: el, start: "top 86%", once: true },
      },
    );
  }

  for (const heading of all(root, "[data-split]")) {
    if (inView(heading, 0.95)) continue;
    SplitText.create(heading, {
      type: "lines",
      mask: "lines",
      autoSplit: true,
      onSplit(self) {
        return gsap.from(self.lines, {
          yPercent: 110,
          duration: 0.55,
          stagger: 0.07,
          ease: "power2.out",
          scrollTrigger: { trigger: heading, start: "top 88%", once: true },
        });
      },
    });
  }

  // The three bars of the mark draw in before every section label: the page's punctuation.
  for (const mark of all<SVGElement>(root, ".mark-bars")) {
    if (inView(mark, 0.95)) continue;
    gsap.from(all(mark, "rect"), {
      scaleX: 0,
      duration: 0.18,
      stagger: 0.04,
      ease: "power2.out",
      scrollTrigger: { trigger: mark, start: "top 90%", once: true },
    });
  }
}

function decider(root: HTMLElement) {
  const flow = root.querySelector<HTMLElement>("#decider .flow");
  if (!flow || inView(flow, 0.6)) return;
  const ms = flow.querySelector<HTMLElement>("[data-count]");
  const target = ms ? Number(ms.dataset.count) : 0;
  const counter = { value: 0 };
  if (ms) ms.textContent = "0";
  const tl = gsap.timeline({ scrollTrigger: { trigger: flow, start: "top 72%", once: true } });
  tl.from(all(flow, ".flow-chip"), {
    x: -28,
    opacity: 0,
    duration: 0.4,
    stagger: 0.08,
    ease: "power2.out",
  })
    .fromTo(
      flow.querySelector(".flow-orb"),
      { scale: 1 },
      { scale: 1.04, duration: 0.18, yoyo: true, repeat: 1, ease: "power2.inOut" },
      ">-0.1",
    )
    .from(
      all(flow, ".flow-bar"),
      { scaleX: 0, duration: 0.9, stagger: 0.1, ease: "power2.out" },
      "<0.15",
    );
  if (ms) {
    tl.to(
      counter,
      {
        value: target,
        duration: 1.2,
        ease: "power2.out",
        onUpdate: () => {
          ms.textContent = String(Math.round(counter.value));
        },
      },
      "<",
    );
  }
}

function pathOfOneEdit(root: HTMLElement) {
  const list = root.querySelector<HTMLElement>("#path ol");
  const line = root.querySelector<SVGPathElement>("#path .path-line path");
  if (!list || !line) return;
  const steps = all(list, ".path-step");
  const dots = all(list, ".path-dot");
  const update = (progress: number) => {
    dots.forEach((dot, index) => {
      dot.classList.toggle("is-reached", index / Math.max(dots.length - 1, 1) <= progress + 0.02);
    });
  };
  update(0);
  gsap.fromTo(
    line,
    { drawSVG: "0%" },
    {
      drawSVG: "100%",
      ease: "none",
      scrollTrigger: {
        trigger: list,
        start: "top 78%",
        end: "bottom 48%",
        scrub: 0.4,
        onUpdate: (self) => update(self.progress),
      },
    },
  );
  gsap.from(steps, {
    y: 14,
    opacity: 0,
    duration: 0.35,
    stagger: 0.08,
    ease: "power2.out",
    scrollTrigger: { trigger: list, start: "top 82%", once: true },
  });
}

function receiptPrint(root: HTMLElement) {
  const slip = root.querySelector<HTMLElement>(".receipt-print");
  if (!slip || inView(slip, 0.7)) return;
  const trigger = { trigger: slip, start: "top 75%", once: true };
  gsap.fromTo(
    slip,
    { clipPath: "inset(0 0 100% 0)" },
    {
      clipPath: "inset(0 0 0% 0)",
      duration: 0.7,
      ease: "power2.inOut",
      clearProps: "clipPath",
      scrollTrigger: trigger,
    },
  );
  gsap.from(all(slip, "li, tr"), {
    opacity: 0,
    y: 6,
    duration: 0.3,
    delay: 0.55,
    stagger: 0.05,
    ease: "power2.out",
    scrollTrigger: trigger,
  });
}

function terminal(root: HTMLElement) {
  const term = root.querySelector<HTMLElement>("[data-terminal]");
  if (!term || inView(term, 0.85)) return;
  const full = term.textContent ?? "";
  term.textContent = "";
  ScrollTrigger.create({
    trigger: term,
    start: "top 85%",
    once: true,
    onEnter: () => {
      gsap.to(term, { text: { value: full, delimiter: "" }, duration: 1.4, ease: "none" });
    },
  });
}

function differentArrows(root: HTMLElement) {
  for (const path of all<SVGPathElement>(root, ".diff-arrow path")) {
    if (inView(path)) continue;
    gsap.from(path, {
      drawSVG: "0%",
      duration: 0.5,
      ease: "power2.out",
      scrollTrigger: { trigger: path, start: "top 88%", once: true },
    });
  }
}

function closingDrift(root: HTMLElement) {
  const contours = root.querySelector<HTMLElement>('[aria-labelledby="cta-title"] .contours');
  if (!contours) return;
  // The one ambient motion on the page: 12 seconds, a few pixels, faint.
  gsap.fromTo(
    contours,
    { scale: 1.06, x: 0, y: 0 },
    { x: -18, y: 10, duration: 12, ease: "sine.inOut", repeat: -1, yoyo: true },
  );
}

const SCATTER = [
  { x: 70, y: 250, r: -8 },
  { x: 300, y: 36, r: 6 },
  { x: 520, y: 330, r: -5 },
  { x: 120, y: 360, r: 7 },
  { x: 760, y: 300, r: -6 },
] as const;
const COLUMN_X = 690;
const COLUMN_Y = 30;
const COLUMN_STEP = 52;

/** The pinned story: one map, read, questioned, answered. Wide screens only. */
function story(root: HTMLElement) {
  const block = root.querySelector<HTMLElement>("[data-story]");
  const stage = block?.querySelector<HTMLElement>(".story-stage");
  if (!block || !stage) return () => undefined;
  block.classList.add("is-on");

  const strips = all<SVGGElement>(stage, ".st-strip");
  const bbox = stage.querySelector<SVGElement>(".st-bbox");
  const edits = all<SVGElement>(stage, ".st-edit");
  const quick = edits.filter((el) => el.dataset.kind !== "deleted");
  const deleted = edits.filter((el) => el.dataset.kind === "deleted");
  const rings = stage.querySelector<SVGGElement>(".st-rings");
  const rows = all<SVGGElement>(stage, ".st-ring");
  const draft = stage.querySelector<SVGGElement>(".st-draft");
  const draftLines = stage.querySelector<SVGGElement>(".st-draft-lines");
  const mapper = stage.querySelector<SVGElement>(".st-mapper");
  const scenes = all(stage, ".story-scene");

  strips.forEach((strip, index) => {
    const from = SCATTER[index] ?? SCATTER[0];
    gsap.set(strip, { x: from.x, y: from.y, rotation: from.r, opacity: 0, svgOrigin: "0 0" });
  });
  gsap.set(bbox, { opacity: 0, scale: 1.35 });
  gsap.set(quick, { opacity: 0, scale: 0 });
  gsap.set(deleted, { opacity: 0 });
  gsap.set(rings, { opacity: 0 });
  rows.forEach((row) => gsap.set(row.querySelector(".st-fill"), { drawSVG: "0% 0%" }));
  gsap.set(draft, { opacity: 0 });
  gsap.set(draftLines, { opacity: 0 });
  gsap.set(mapper, { opacity: 0 });

  const tl = gsap.timeline({
    defaults: { ease: "power2.inOut" },
    scrollTrigger: {
      trigger: stage,
      start: "top top+=76",
      end: "+=3000",
      pin: true,
      scrub: 0.6,
      anticipatePin: 1,
      invalidateOnRefresh: true,
      snap: {
        snapTo: "labels",
        directional: false,
        duration: { min: 0.2, max: 0.6 },
        delay: 0.12,
        ease: "power2.inOut",
      },
    },
  });

  // Labels sit where each scene is complete, so the scroll settles on a finished picture.
  tl.addLabel("start", 0)
    .to(strips, { opacity: 1, duration: 0.4, stagger: 0.06 }, 0)
    .to(bbox, { opacity: 1, scale: 1, duration: 1 }, 0)
    .to(quick, { opacity: 1, scale: 1, duration: 0.5, stagger: 0.04 }, 0.3)
    .to(deleted, { opacity: 1, duration: 0.4 }, 0.8)
    .to(
      strips,
      {
        x: COLUMN_X,
        y: (index: number) => COLUMN_Y + index * COLUMN_STEP,
        rotation: 0,
        duration: 1,
        stagger: 0.08,
      },
      1.4,
    )
    .addLabel("read", 2.8)
    .to(scenes[0] ?? null, { opacity: 0, duration: 0.3 }, 3)
    .to(scenes[1] ?? null, { opacity: 1, duration: 0.3 }, 3.2)
    .to(rings, { opacity: 1, duration: 0.4 }, 3.2);
  rows.forEach((row, index) => {
    const share = Number(row.dataset.p ?? 0);
    tl.to(
      row.querySelector(".st-fill"),
      { drawSVG: `0% ${Math.round(share * 100)}%`, duration: 0.6 },
      3.5 + index * 0.12,
    );
  });
  tl.addLabel("ask", 5.3)
    .to(scenes[1] ?? null, { opacity: 0, duration: 0.3 }, 5.5)
    .to(scenes[2] ?? null, { opacity: 1, duration: 0.3 }, 5.7)
    .to(rings, { opacity: 0.18, duration: 0.5 }, 5.7)
    .to(draft, { opacity: 1, duration: 0.4 }, 5.9)
    .fromTo(draftLines, { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.6 }, 6.2)
    .to(mapper, { opacity: 1, duration: 0.2 }, 5.9)
    .to(
      mapper,
      {
        motionPath: {
          path: "#st-river",
          align: "#st-river",
          alignOrigin: [0.5, 0.5],
          start: 0,
          end: 0.62,
        },
        duration: 2.4,
        ease: "none",
      },
      6,
    )
    .to({}, { duration: 1 }, 8.4)
    .addLabel("write", 9.4);

  return () => block.classList.remove("is-on");
}

function build(root: HTMLElement) {
  const html = document.documentElement;
  const mm = gsap.matchMedia();
  mm.add(
    {
      // The callback runs when any condition matches, so "any" makes it run on every screen.
      any: "(min-width: 1px)",
      desktop: "(min-width: 1100px)",
      reduce: "(prefers-reduced-motion: reduce)",
    },
    (context) => {
      const conditions = context.conditions as { desktop: boolean; reduce: boolean };
      if (conditions.reduce || readLessMotion()) return undefined;
      html.dataset.motion = "gsap";
      revealsAndHeadings(root);
      decider(root);
      receiptPrint(root);
      terminal(root);
      differentArrows(root);
      closingDrift(root);
      let undoStory: () => void = () => undefined;
      if (conditions.desktop) {
        pathOfOneEdit(root);
        undoStory = story(root);
      }
      return () => {
        undoStory();
        delete html.dataset.motion;
      };
    },
  );
  return mm;
}

/**
 * Starts the motion for one mounted home page and returns a function that undoes all of it. The
 * footer switch calls the same path: it tears everything down and rebuilds, so the page lands
 * exactly where the reader was.
 */
export function attachLandingMotion(root: HTMLElement): () => void {
  restoreLessMotion();
  let mm = build(root);
  const onSwitch = () => {
    mm.revert();
    mm = build(root);
    ScrollTrigger.refresh();
  };
  window.addEventListener(LESS_MOTION_EVENT, onSwitch);
  void document.fonts?.ready.then(() => ScrollTrigger.refresh());
  return () => {
    window.removeEventListener(LESS_MOTION_EVENT, onSwitch);
    mm.revert();
    delete document.documentElement.dataset.motion;
  };
}
