import {
  ArrowUpRight,
  Eye,
  Heart,
  Monitor,
  ShieldCheck,
  Terminal,
  UserCheck,
  Users,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { useBranding } from "../branding/branding";
import { EvidenceStrip, SAMPLE_DIFFS } from "../components/evidence/EvidenceStrip";
import { ReceiptView } from "../components/receipt/ReceiptView";
import { useHydrated } from "../lib/useHydrated";
import {
  LESS_MOTION_EVENT,
  readLessMotion,
  restoreLessMotion,
  systemPrefersReducedMotion,
} from "../motion/less";
import { withChangesetLink } from "./ChangesetLink";
import { DeciderFlow } from "./art/DeciderFlow";
import { LivingMap } from "./art/LivingMap";
import { StoryStage, STORY_CHANGESET } from "./art/StoryStage";
import { AskVignette, DecideVignette, GatherVignette } from "./art/Vignettes";
import { copy, fill, REPO_URL } from "./copy";
import "./landing.css";
import { Reveal, SpotlightCard } from "./motion";
import numbers from "./numbers.json";
import { SAMPLE_RECEIPT } from "./sample-receipt";

const WRAP = "mx-auto max-w-[1200px]";
const SECTION = "px-4 py-20 md:py-32";

function Heading({
  id,
  eyebrow,
  title,
  className = "",
}: {
  id: string;
  eyebrow: string;
  title: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <p className="eyebrow m-0 flex items-center gap-2.5">
        <MarkBars />
        {eyebrow}
      </p>
      <h2
        id={id}
        data-split
        className="display mt-3 mb-0 max-w-[22ch] text-[clamp(2rem,4.2vw,3.4rem)] text-ink"
      >
        {title}
      </h2>
    </div>
  );
}

/** The three bars of the logo mark, small, in front of a section label; the motion draws them in. */
function MarkBars() {
  return (
    <svg
      viewBox="0 0 24 21"
      width="18"
      height="16"
      aria-hidden="true"
      focusable="false"
      className="mark-bars shrink-0"
    >
      <rect className="fill-accent" x="0" y="0" width="12" height="5" rx="2.5" />
      <rect className="fill-ink" x="0" y="8" width="24" height="5" rx="2.5" />
      <rect className="fill-ink" x="0" y="16" width="18" height="5" rx="2.5" />
    </svg>
  );
}

function Section({
  id,
  titleId,
  className = "",
  children,
}: {
  id?: string;
  titleId: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={titleId} className={`${SECTION} ${className}`}>
      <div className={WRAP}>{children}</div>
    </section>
  );
}

const STEP_ART = [GatherVignette, AskVignette, DecideVignette] as const;

function PackPicker() {
  const name = useId();
  const [pack, setPack] = useState<string>(copy.communities.packs[0].id);
  const current = copy.communities.packs.find((item) => item.id === pack);
  return (
    <fieldset className="card m-0 border p-6 md:p-8">
      <legend className="eyebrow px-2">{copy.communities.packsLabel}</legend>
      <div className="flex flex-wrap gap-2">
        {copy.communities.packs.map((item) => (
          <label key={item.id} className="relative cursor-pointer">
            <input
              type="radio"
              name={name}
              value={item.id}
              checked={pack === item.id}
              onChange={() => setPack(item.id)}
              className="peer sr-only"
              data-testid={`pack-${item.id}`}
            />
            <span className="inline-flex min-h-11 items-center rounded-full border border-control-border px-4 text-ink transition-colors peer-checked:border-accent peer-checked:bg-accent peer-checked:text-accent-fg peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--color-focus)]">
              {item.title}
            </span>
          </label>
        ))}
      </div>
      <p className="mt-6 mb-0 min-h-[5.5rem] text-lg text-ink-2" aria-live="polite">
        {current?.body}
      </p>
    </fieldset>
  );
}

/** The home page. Static markup first; the map, the strip and the cards come alive once it is live. */
export function Landing() {
  // The strip is a still frame in the static HTML and starts moving once the page is live.
  const live = useHydrated();
  // The workspace's own paragraph replaces the built-in one once the server has answered.
  const paragraph = useBranding()?.community_paragraph ?? copy.communities.body;
  const lead = copy.headline.endsWith(copy.headlineEmphasis)
    ? copy.headline.slice(0, copy.headline.length - copy.headlineEmphasis.length)
    : `${copy.headline} `;
  const root = useRef<HTMLDivElement>(null);

  // The motion module is a separate chunk. It is fetched only when motion is wanted, after the page
  // has painted, and the page is complete without it.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let stop: (() => void) | undefined;
    let started = false;
    let cancelled = false;
    const start = () => {
      if (started || systemPrefersReducedMotion() || readLessMotion()) return;
      started = true;
      void import("../motion/landing").then((module) => {
        if (cancelled) return;
        stop = module.attachLandingMotion(el);
      });
    };
    restoreLessMotion();
    const schedule = window.requestIdleCallback
      ? (callback: () => void) => window.requestIdleCallback(callback, { timeout: 600 })
      : (callback: () => void) => window.setTimeout(callback, 120);
    schedule(start);
    window.addEventListener(LESS_MOTION_EVENT, start);
    return () => {
      cancelled = true;
      window.removeEventListener(LESS_MOTION_EVENT, start);
      stop?.();
    };
  }, []);

  return (
    <div ref={root}>
      <section
        className="relative overflow-hidden px-4 pt-10 pb-20 md:pt-16 md:pb-28"
        aria-labelledby="hero-title"
      >
        <div className="contours" aria-hidden="true" />
        <div
          className={`${WRAP} relative grid items-center gap-12 lg:grid-cols-[5fr_7fr] lg:gap-14`}
        >
          <div>
            <p className="badge m-0">
              <span className="badge-dot" aria-hidden="true" />
              <span className="text-ink">{copy.hero.badge}</span>
              <span aria-hidden="true">&middot;</span>
              <span>{copy.hero.badgeNote}</span>
            </p>
            <h1
              id="hero-title"
              className="display hero-rise mt-6 mb-0 text-[clamp(2.7rem,5.6vw,4.9rem)] text-ink"
            >
              {lead}
              <span className="hl">{copy.headlineEmphasis}</span>
            </h1>
            <p
              className="hero-rise mt-6 mb-0 max-w-[52ch] text-[clamp(1.05rem,1.5vw,1.25rem)] leading-relaxed text-ink-2"
              style={{ animationDelay: "120ms" }}
            >
              {copy.hero.sub}
            </p>
            <div
              className="hero-rise mt-9 flex flex-wrap items-center gap-3"
              style={{ animationDelay: "240ms" }}
            >
              <a href="/queue" className="btn btn-primary" data-testid="hero-primary">
                {copy.hero.primary}{" "}
                <span className="arrow" aria-hidden="true">
                  &rarr;
                </span>
              </a>
              <a href="#how" className="btn btn-ghost">
                {copy.hero.secondary}
              </a>
            </div>
            <p className="mt-5 mb-0 text-sm text-ink-2">{copy.hero.note}</p>
          </div>
          <LivingMap />
        </div>
      </section>

      <section className="border-y border-line bg-surface py-8" aria-label={copy.reads.label}>
        <p className="eyebrow m-0 mb-5 text-center">{copy.reads.label}</p>
        <div className="marquee">
          <div className="marquee-track">
            {copy.reads.items.map((item) => (
              <span key={item} className="marquee-item">
                {item}
              </span>
            ))}
            {copy.reads.items.map((item) => (
              <span key={`again-${item}`} className="marquee-item" aria-hidden="true">
                {item}
              </span>
            ))}
          </div>
        </div>
      </section>

      <Section id="basics" titleId="basics-title">
        <Reveal>
          <Heading id="basics-title" eyebrow={copy.basics.eyebrow} title={copy.basics.title} />
        </Reveal>
        <ul className="mt-14 grid list-none gap-5 p-0 md:grid-cols-3">
          {copy.basics.items.map((item, index) => (
            <li key={item.title} className="m-0">
              <Reveal delay={index * 110} className="h-full">
                <SpotlightCard className="card flex h-full flex-col p-7">
                  <h3 className="display m-0 text-2xl text-ink">{item.title}</h3>
                  <p className="mt-3 mb-0 flex-1 leading-relaxed text-ink-2">{item.body}</p>
                  <p className="mt-5 mb-0">
                    <a
                      href={item.href}
                      rel="noopener noreferrer"
                      className="inline-flex min-h-8 items-center gap-1.5 font-medium text-ink underline underline-offset-4"
                    >
                      {item.link}
                      <ArrowUpRight aria-hidden="true" size={16} strokeWidth={2} />
                    </a>
                  </p>
                </SpotlightCard>
              </Reveal>
            </li>
          ))}
        </ul>
      </Section>

      <Section titleId="problem-title" className="bg-surface-2">
        <div className="grid gap-10 lg:grid-cols-[7fr_5fr] lg:gap-20">
          <Reveal>
            <Heading id="problem-title" eyebrow={copy.problem.eyebrow} title={copy.problem.title} />
          </Reveal>
          <Reveal delay={120} className="space-y-5 text-lg leading-relaxed text-ink-2 lg:pt-10">
            {copy.problem.body.map((paragraph) => (
              <p key={paragraph} className="m-0">
                {paragraph}
              </p>
            ))}
          </Reveal>
        </div>
      </Section>

      <Section id="how" titleId="how-title">
        <Reveal>
          <Heading id="how-title" eyebrow={copy.how.eyebrow} title={copy.how.title} />
        </Reveal>
        <div className="mt-14">
          <StoryStage
            scenes={copy.story.scenes}
            footnote={withChangesetLink(copy.story.footnote, STORY_CHANGESET)}
          />
        </div>
        <ol className="grid list-none gap-5 p-0 md:grid-cols-3">
          {copy.how.items.map((item, index) => {
            const Art = STEP_ART[index] ?? GatherVignette;
            return (
              <li key={item.title} className="m-0">
                <Reveal delay={index * 110} className="h-full">
                  <SpotlightCard className="card h-full p-6 md:p-7">
                    <p className="eyebrow m-0">{String(index + 1).padStart(2, "0")}</p>
                    <div className="mt-4 rounded-2xl bg-surface-2 p-4">
                      <Art />
                    </div>
                    <h3 className="display mt-6 mb-0 text-2xl text-ink">{item.title}</h3>
                    <p className="mt-3 mb-0 leading-relaxed text-ink-2">{item.body}</p>
                  </SpotlightCard>
                </Reveal>
              </li>
            );
          })}
        </ol>
      </Section>

      <Section id="decider" titleId="decider-title" className="bg-surface-2">
        <Reveal>
          <Heading id="decider-title" eyebrow={copy.decider.eyebrow} title={copy.decider.title} />
          <p className="mt-5 mb-0 max-w-[64ch] text-lg leading-relaxed text-ink-2">
            {copy.decider.body}
          </p>
        </Reveal>
        <Reveal delay={100} className="mt-14">
          <DeciderFlow />
        </Reveal>
        <h3 className="display mt-20 mb-0 text-2xl text-ink">{copy.decider.impactTitle}</h3>
        <ul className="mt-6 grid list-none gap-5 p-0 md:grid-cols-3">
          {copy.decider.impact.map((item, index) => (
            <li key={item.title} className="m-0">
              <Reveal delay={index * 110} className="h-full">
                <SpotlightCard className="card h-full p-7">
                  <h4 className="display m-0 text-xl text-ink">{item.title}</h4>
                  <p className="mt-3 mb-0 leading-relaxed text-ink-2">
                    {fill(item.body, {
                      ms: Math.round(numbers.demo.median_model_ms),
                      cases: numbers.demo.cases,
                      unknown: numbers.demo.unknown_readings,
                      readings: numbers.demo.readings,
                    })}
                  </p>
                </SpotlightCard>
              </Reveal>
            </li>
          ))}
        </ul>
        <Reveal>
          <p className="mt-10 mb-0 max-w-[70ch] text-lg leading-relaxed text-ink">
            {copy.decider.why}
          </p>
        </Reveal>
      </Section>

      <Section id="path" titleId="path-title">
        <Reveal>
          <Heading id="path-title" eyebrow={copy.path.eyebrow} title={copy.path.title} />
        </Reveal>
        <div className="relative mt-14">
          <svg
            className="path-line pointer-events-none absolute top-[22px] right-[8.5%] left-[8.5%] h-1"
            viewBox="0 0 1000 4"
            preserveAspectRatio="none"
            aria-hidden="true"
            focusable="false"
          >
            <path
              d="M0 2H1000"
              fill="none"
              stroke="var(--color-accent)"
              strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
          <ol className="relative grid list-none gap-8 p-0 sm:grid-cols-3 lg:grid-cols-6 lg:gap-4">
            {copy.path.steps.map((step, index) => {
              const human = step.name === "You decide" || step.name === "You post";
              return (
                <li key={step.name} className="path-step m-0 text-center">
                  <Reveal delay={index * 90}>
                    <span
                      data-human={human ? "true" : undefined}
                      className={`path-dot mx-auto inline-grid size-11 place-items-center rounded-full font-mono text-sm ${
                        human
                          ? "bg-accent text-accent-fg"
                          : "border border-line bg-surface text-ink"
                      }`}
                      aria-hidden="true"
                    >
                      {index + 1}
                    </span>
                    <h3 className="display mt-4 mb-0 text-lg text-ink">{step.name}</h3>
                    <p className="mx-auto mt-2 mb-0 max-w-[22ch] text-sm leading-relaxed text-ink-2">
                      {step.body}
                    </p>
                  </Reveal>
                </li>
              );
            })}
          </ol>
        </div>
      </Section>

      <Section titleId="strip-title" className="bg-surface-2">
        <div className="grid items-center gap-10 lg:grid-cols-[5fr_6fr] lg:gap-16">
          <Reveal>
            <Heading id="strip-title" eyebrow={copy.strip.eyebrow} title={copy.strip.title} />
            <p className="mt-5 mb-0 max-w-[44ch] text-lg leading-relaxed text-ink-2">
              {copy.strip.caption}
            </p>
          </Reveal>
          <Reveal delay={120}>
            <div className="card p-5 md:p-7">
              <EvidenceStrip diffs={SAMPLE_DIFFS} loop={live} label={copy.strip.label} />
            </div>
          </Reveal>
        </div>
      </Section>

      <Section id="receipt" titleId="receipt-title">
        <Reveal>
          <Heading id="receipt-title" eyebrow={copy.receipt.eyebrow} title={copy.receipt.title} />
          <p className="mt-5 mb-0 max-w-[60ch] text-lg leading-relaxed text-ink-2">
            {copy.receipt.body}
          </p>
        </Reveal>
        <Reveal delay={100}>
          <div className="card receipt-print mt-10 p-4 md:p-8">
            <ReceiptView receipt={SAMPLE_RECEIPT} headingLevel={3} embedded />
          </div>
          <p className="mt-4 mb-0 text-sm text-ink-2">{copy.receipt.disclosure}</p>
        </Reveal>
      </Section>

      <Section titleId="promises-title" className="bg-surface-2">
        <Reveal>
          <Heading
            id="promises-title"
            eyebrow={copy.promises.eyebrow}
            title={copy.promises.title}
          />
        </Reveal>
        <ul className="mt-14 grid list-none gap-5 p-0 md:grid-cols-3">
          {copy.promises.items.map((item, index) => {
            const Icon = [ShieldCheck, Eye, UserCheck][index] ?? ShieldCheck;
            return (
              <li key={item.title} className="m-0">
                <Reveal delay={index * 110} className="h-full">
                  <SpotlightCard className="card h-full p-7">
                    <span className="inline-grid size-12 place-items-center rounded-2xl bg-accent text-accent-fg">
                      <Icon aria-hidden="true" size={24} strokeWidth={1.75} />
                    </span>
                    <h3 className="display mt-6 mb-0 text-2xl text-ink">{item.title}</h3>
                    <p className="mt-3 mb-0 leading-relaxed text-ink-2">{item.body}</p>
                  </SpotlightCard>
                </Reveal>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section id="communities" titleId="communities-title">
        <div className="grid items-start gap-10 lg:grid-cols-[6fr_6fr] lg:gap-16">
          <Reveal>
            <Heading
              id="communities-title"
              eyebrow={copy.communities.eyebrow}
              title={copy.communities.title}
            />
            <p
              className="mt-5 mb-0 max-w-[52ch] text-lg leading-relaxed text-ink-2"
              data-testid="community-paragraph"
            >
              {paragraph}
            </p>
            <p className="mt-6 mb-0">
              <a
                href={`${REPO_URL}/blob/main/patterns/README.md`}
                className="font-medium text-ink underline underline-offset-4"
                rel="noopener"
              >
                {copy.communities.link}
              </a>
            </p>
            <p className="mt-3 mb-0 text-sm text-ink-2">{copy.communities.inviteOnly}</p>
          </Reveal>
          <Reveal delay={120}>
            <PackPicker />
          </Reveal>
        </div>
      </Section>

      <Section id="engine" titleId="engine-title" className="bg-surface-2">
        <Reveal>
          <Heading id="engine-title" eyebrow={copy.engine.eyebrow} title={copy.engine.title} />
          <p className="mt-5 mb-0 max-w-[60ch] text-lg leading-relaxed text-ink-2">
            {copy.engine.body}
          </p>
        </Reveal>
        <ul className="mt-14 grid list-none gap-5 p-0 md:grid-cols-3">
          {copy.engine.items.map((item, index) => (
            <li key={item.name} className="m-0">
              <Reveal delay={index * 110} className="h-full">
                <SpotlightCard className="card flex h-full flex-col p-7">
                  <p className="eyebrow m-0">{item.role}</p>
                  <h3 className="display mt-3 mb-0 text-2xl text-ink">{item.name}</h3>
                  <p className="mt-3 mb-0 flex-1 leading-relaxed text-ink-2">{item.body}</p>
                  <p className="mt-5 mb-0 flex flex-wrap gap-x-5 gap-y-1">
                    {item.links.map((link) => (
                      <a
                        key={link.href}
                        href={link.href}
                        rel="noopener noreferrer"
                        className="inline-flex min-h-8 items-center gap-1.5 font-medium text-ink underline underline-offset-4"
                      >
                        {link.label}
                        <ArrowUpRight aria-hidden="true" size={16} strokeWidth={2} />
                      </a>
                    ))}
                  </p>
                </SpotlightCard>
              </Reveal>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="use" titleId="modes-title">
        <Reveal>
          <Heading id="modes-title" eyebrow={copy.modes.eyebrow} title={copy.modes.title} />
          <p className="mt-5 mb-0 max-w-[60ch] text-lg leading-relaxed text-ink-2">
            {copy.modes.body}
          </p>
        </Reveal>
        <ul className="mt-14 grid list-none gap-5 p-0 md:grid-cols-3">
          {copy.modes.items.map((item, index) => {
            const Icon = [Monitor, Users, Terminal][index] ?? Monitor;
            return (
              <li key={item.name} className="m-0">
                <Reveal delay={index * 110} className="h-full">
                  <SpotlightCard className="card flex h-full flex-col p-7">
                    <span className="inline-grid size-12 place-items-center rounded-2xl bg-accent text-accent-fg">
                      <Icon aria-hidden="true" size={24} strokeWidth={1.75} />
                    </span>
                    <p className="eyebrow m-0 mt-6">{item.who}</p>
                    <h3 className="display mt-2 mb-0 text-2xl text-ink">{item.name}</h3>
                    <ul className="mt-4 mb-0 flex list-none flex-col gap-3 p-0">
                      {item.points.map((point) => (
                        <li key={point} className="m-0 flex items-start gap-2.5 text-ink-2">
                          <span
                            aria-hidden="true"
                            className="mt-2 size-1.5 shrink-0 rounded-full bg-accent"
                          />
                          {point}
                        </li>
                      ))}
                    </ul>
                  </SpotlightCard>
                </Reveal>
              </li>
            );
          })}
        </ul>
        <Reveal>
          <pre className="terminal mt-10" data-terminal>
            {copy.modes.terminal}
          </pre>
        </Reveal>
        <Reveal>
          <p className="mt-10 mb-0 flex flex-wrap gap-3">
            <a href="/queue" className="btn btn-primary">
              {copy.modes.openQueue}
            </a>
            <a href="/login" className="btn btn-ghost">
              {copy.modes.signIn}
            </a>
            <a href="/about#run" className="btn btn-ghost">
              {copy.modes.docs}
            </a>
          </p>
        </Reveal>
      </Section>

      <Section id="different" titleId="different-title" className="bg-surface-2">
        <Reveal>
          <Heading
            id="different-title"
            eyebrow={copy.different.eyebrow}
            title={copy.different.title}
          />
        </Reveal>
        <ul className="mt-14 grid list-none gap-5 p-0">
          {copy.different.rows.map((row, index) => (
            <li key={row.other} className="m-0">
              <Reveal delay={index * 90}>
                <div className="card grid gap-6 p-6 md:grid-cols-[4fr_4fr_5fr] md:items-center md:p-8">
                  <div>
                    <p className="eyebrow m-0">{row.other}</p>
                    <p className="mt-2 mb-0 text-ink-2">{row.theirs}</p>
                  </div>
                  <svg
                    viewBox="0 0 48 14"
                    width="48"
                    height="14"
                    aria-hidden="true"
                    focusable="false"
                    className="diff-arrow hidden md:block"
                  >
                    <path d="M2 7H44M38 2l6 5-6 5" />
                  </svg>
                  <p className="m-0 text-lg text-ink">{row.ours}</p>
                </div>
              </Reveal>
            </li>
          ))}
        </ul>
      </Section>

      <Section titleId="straight-title">
        <Reveal>
          <div className="card grid gap-8 p-8 md:p-12 lg:grid-cols-[6fr_4fr] lg:items-end">
            <div>
              <Heading
                id="straight-title"
                eyebrow={copy.straight.eyebrow}
                title={copy.straight.title}
              />
              <p className="mt-5 mb-0 max-w-[60ch] text-lg leading-relaxed text-ink-2">
                {copy.straight.body}
              </p>
            </div>
            <p className="m-0 lg:text-right">
              <a href="/about#numbers" className="btn btn-ghost" data-testid="scorecard-link">
                {copy.straight.link}{" "}
                <span className="arrow" aria-hidden="true">
                  &rarr;
                </span>
              </a>
            </p>
          </div>
        </Reveal>
      </Section>

      <Section id="open-source" titleId="open-source-title" className="bg-surface-2">
        <div className="grid items-center gap-10 lg:grid-cols-[6fr_5fr] lg:gap-16">
          <Reveal>
            <Heading
              id="open-source-title"
              eyebrow={copy.openSource.eyebrow}
              title={copy.openSource.title}
            />
            <p className="mt-5 mb-0 max-w-[56ch] text-lg leading-relaxed text-ink-2">
              {copy.openSource.body}
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a href={REPO_URL} className="btn btn-primary" rel="noopener noreferrer">
                {copy.openSource.github}
              </a>
              <a href="/about#run" className="btn btn-ghost">
                {copy.openSource.run}
              </a>
              <a href="/docs/" className="btn btn-ghost" data-testid="read-docs">
                {copy.openSource.docs}
              </a>
              <a
                href={`${REPO_URL}/blob/main/CONTRIBUTING.md`}
                className="btn btn-ghost"
                rel="noopener noreferrer"
              >
                {copy.openSource.contribute}
              </a>
            </div>
          </Reveal>
          <Reveal delay={120}>
            <ul className="card m-0 flex list-none flex-col gap-4 p-7">
              {copy.openSource.points.map((point) => (
                <li key={point} className="m-0 flex items-start gap-3 text-lg text-ink">
                  <span
                    aria-hidden="true"
                    className="mt-1 inline-grid size-6 shrink-0 place-items-center rounded-full bg-accent text-accent-fg"
                  >
                    <svg viewBox="0 0 16 16" width="12" height="12" fill="none">
                      <path
                        d="M3 8.5l3 3 7-7"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                  {point}
                </li>
              ))}
            </ul>
          </Reveal>
        </div>
      </Section>

      <Section id="maker" titleId="maker-title">
        <Reveal>
          <div className="card grid gap-8 p-8 md:p-12 lg:grid-cols-[6fr_5fr] lg:items-center">
            <div>
              <Heading id="maker-title" eyebrow={copy.maker.eyebrow} title={copy.maker.title} />
              <p className="mt-5 mb-0 max-w-[56ch] text-lg leading-relaxed text-ink-2">
                {copy.maker.body}
              </p>
            </div>
            <ul className="m-0 flex list-none flex-col gap-3 p-0" data-testid="maker-links">
              {[
                [copy.maker.hackathon, copy.maker.links.hackathon],
                [copy.maker.linkedin, copy.maker.links.linkedin],
                [copy.maker.builder, copy.maker.links.builder],
                [copy.maker.email, copy.maker.links.email],
                [copy.maker.sponsor, copy.maker.links.sponsor],
              ].map(([label, href]) => (
                <li key={href} className="m-0">
                  <a
                    href={href}
                    rel="noopener noreferrer"
                    className="inline-flex min-h-9 items-center gap-1.5 text-lg font-medium text-ink underline underline-offset-4"
                  >
                    {href === copy.maker.links.sponsor ? (
                      <Heart aria-hidden="true" size={18} strokeWidth={2} className="text-accent" />
                    ) : null}
                    {label}
                    <ArrowUpRight aria-hidden="true" size={18} strokeWidth={2} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </Section>

      <section className="relative overflow-hidden px-4 py-24 md:py-36" aria-labelledby="cta-title">
        <div className="contours" aria-hidden="true" />
        <Reveal className={`${WRAP} relative text-center`}>
          <h2
            id="cta-title"
            data-split
            className="display mx-auto mt-0 mb-0 max-w-[18ch] text-[clamp(2.2rem,5vw,4rem)] text-ink"
          >
            {copy.cta.title}
          </h2>
          <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
            <a href="/queue" className="btn btn-primary">
              {copy.cta.primary}{" "}
              <span className="arrow" aria-hidden="true">
                &rarr;
              </span>
            </a>
            <a href="/login" className="btn btn-ghost">
              {copy.cta.secondary}
            </a>
          </div>
        </Reveal>
      </section>
    </div>
  );
}
