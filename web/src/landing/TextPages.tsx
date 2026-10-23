import { useState, useSyncExternalStore, type ReactNode } from "react";

import { ScrollRegion } from "../components/case/ScrollRegion";
import { HostedViewOnly } from "../components/shell/ModeBanner";
import { t } from "../i18n";
import { copy, fill, REPO_URL } from "./copy";
import "./landing.css";
import { Reveal } from "./motion";
import numbers from "./numbers.json";
import { isHostedDemo } from "./site";

type Share = { k: number; n: number; lower: number; upper: number };

/** "0.85 (0.82 to 0.89)": a share with its 95 percent interval, written without dashes. */
export function formatShare(p: Share): string {
  if (p.n === 0) return "no data";
  const f = (v: number) => v.toFixed(2);
  return `${f(p.k / p.n)} (${f(p.lower)} to ${f(p.upper)})`;
}

interface Block {
  id?: string;
  title: string;
  paragraphs: readonly string[];
}

function Prose({ block, children }: { block: Block; children?: ReactNode }) {
  return (
    <Reveal as="section" className="mt-16">
      <h2 id={block.id} className="display m-0 text-[clamp(1.6rem,3vw,2.2rem)] text-ink">
        {block.title}
      </h2>
      {block.paragraphs.map((paragraph) => (
        <p key={paragraph} className="mt-4 mb-0 text-lg leading-relaxed text-ink-2">
          {paragraph}
        </p>
      ))}
      {children}
    </Reveal>
  );
}

function Frame({ title, lead, children }: { title: string; lead?: string; children: ReactNode }) {
  return (
    <article className="relative overflow-hidden px-4 py-16 md:py-28" aria-labelledby="page-title">
      <div className="contours" aria-hidden="true" />
      <div className="relative mx-auto max-w-[760px]">
        <h1 id="page-title" className="display m-0 text-[clamp(2.6rem,6vw,4.4rem)] text-ink">
          {title}
        </h1>
        {lead ? <p className="mt-6 mb-0 text-xl leading-relaxed text-ink-2">{lead}</p> : null}
        {children}
      </div>
    </article>
  );
}

function Figure({
  label,
  value,
  detail,
  note,
  share,
}: {
  label: string;
  value: string;
  detail: string;
  note: string;
  share?: Share;
}) {
  return (
    <div className="card p-5">
      <p className="m-0 text-sm text-ink-2">{label}</p>
      <p className="mt-1 mb-0 font-mono text-2xl font-semibold tabular-nums text-ink">{value}</p>
      {share && share.n > 0 ? (
        <div className="relative mt-3 h-2.5 rounded-full bg-surface-2" aria-hidden="true">
          <div
            className="flow-bar absolute inset-y-0 left-0 rounded-full"
            data-state="yes"
            style={{ width: `${(share.k / share.n) * 100}%` }}
          />
          <div
            className="absolute -inset-y-0.5 rounded-full border border-ink/50"
            style={{
              left: `${share.lower * 100}%`,
              width: `${(share.upper - share.lower) * 100}%`,
            }}
          />
        </div>
      ) : null}
      <p className="mt-2 mb-0 font-mono text-xs text-ink-2">{detail}</p>
      <p className="mt-2 mb-0 text-sm text-ink-2">{note}</p>
    </div>
  );
}

function Glance() {
  const demo = numbers.demo;
  const values = {
    cases: demo.cases,
    perCase: demo.questions_per_case,
    seconds: (demo.median_model_ms / 1000).toFixed(2),
    unknown: demo.unknown_readings,
    readings: demo.readings,
    lanes: Object.keys(demo.lanes).length,
  };
  const tiles = [
    copy.numbers.glance.cases,
    copy.numbers.glance.questions,
    copy.numbers.glance.speed,
    copy.numbers.glance.unknown,
    copy.numbers.glance.lanes,
    copy.numbers.glance.writes,
  ];
  return (
    <>
      <h2 id="glance" className="display m-0 text-[clamp(1.6rem,3vw,2.2rem)] text-ink">
        {copy.numbers.glanceTitle}
      </h2>
      <p className="mt-4 mb-0 text-lg leading-relaxed text-ink-2">{copy.numbers.glanceIntro}</p>
      <ul className="mt-6 grid list-none gap-4 p-0 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((tile) => (
          <li key={tile.label} className="card m-0 p-5" data-testid="glance-tile">
            <p className="display m-0 text-[2.4rem] leading-none text-ink">
              {fill(tile.value, values)}
            </p>
            <p className="mt-3 mb-0 text-sm leading-relaxed text-ink-2">{tile.label}</p>
          </li>
        ))}
      </ul>
    </>
  );
}

/** A command block with a copy button; the text is a constant, never read from evidence. */
function CommandBlock({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  async function onCopy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false); // the text stays selectable; nothing else to do
    }
  }
  return (
    <div className="card mt-5 overflow-hidden">
      <ScrollRegion label={copy.run.commandLabel}>
        <pre className="m-0 p-5 font-mono text-[13px] leading-6 text-ink">
          <code>{command}</code>
        </pre>
      </ScrollRegion>
      <div className="flex items-center justify-end gap-3 border-t border-line px-4 py-2">
        <span role="status" className="text-sm text-ink-2">
          {copied ? copy.run.copied : ""}
        </span>
        <button
          type="button"
          onClick={() => void onCopy()}
          className="min-h-9 cursor-pointer rounded-full border border-control-border bg-surface px-4 text-sm text-ink hover:bg-surface-2"
        >
          {copy.run.copy}
        </button>
      </div>
    </div>
  );
}

function Scorecard() {
  const n = numbers;
  return (
    <Reveal as="section" className="mt-16">
      <Glance />
      <h2 id="numbers" className="display mt-16 mb-0 text-[clamp(1.6rem,3vw,2.2rem)] text-ink">
        {copy.numbers.title}
      </h2>
      <h3 className="mt-6 mb-0 text-xl font-semibold text-ink">{copy.numbers.sixtyTitle}</h3>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Figure
          label={copy.numbers.items.decided.label}
          value={`${n.pooled_decided.k} of ${n.pooled_decided.n}`}
          detail={formatShare(n.pooled_decided)}
          note={copy.numbers.items.decided.note}
          share={n.pooled_decided}
        />
        <Figure
          label={copy.numbers.items.baseline.label}
          value={`${n.majority_baseline.k} of ${n.majority_baseline.n}`}
          detail={formatShare(n.majority_baseline)}
          note={copy.numbers.items.baseline.note}
          share={n.majority_baseline}
        />
        <Figure
          label={copy.numbers.items.unknown.label}
          value={`${n.unknown_rate.k} of ${n.unknown_rate.n}`}
          detail={formatShare(n.unknown_rate)}
          note={copy.numbers.items.unknown.note}
          share={n.unknown_rate}
        />
        <Figure
          label={copy.numbers.items.nature.label}
          value={`${n.nature_composed.k} of ${n.nature_composed.n}`}
          detail={formatShare(n.nature_composed)}
          note={fill(copy.numbers.items.nature.note, {
            rules: `${n.nature_rules.k} of ${n.nature_rules.n}`,
          })}
          share={n.nature_composed}
        />
      </div>
      <p className="mt-5 mb-0 text-lg text-ink" data-testid="numbers-disclosure">
        {n.labels.text}
      </p>
      <h3 className="mt-8 mb-0 text-xl font-semibold text-ink">{copy.numbers.readTitle}</h3>
      <p className="mt-3 mb-0 text-lg leading-relaxed text-ink-2">{copy.numbers.can}</p>
      <p className="mt-3 mb-0 text-lg leading-relaxed text-ink-2">{copy.numbers.cannot}</p>
    </Reveal>
  );
}

const noSubscription = () => () => {};

/** The view only sentence, shown on the hosted demo only. The server snapshot is false so prerender matches. */
function HostedDemoNote() {
  const hosted = useSyncExternalStore(
    noSubscription,
    () => isHostedDemo(),
    () => false,
  );
  if (!hosted) return null;
  return (
    <p className="mt-6 mb-0 text-lg leading-relaxed text-ink" data-testid="hosted-demo-note">
      <HostedViewOnly />
    </p>
  );
}

export function About() {
  const command = fill(copy.run.command, { repo: REPO_URL });
  return (
    <Frame title={copy.about.title} lead={copy.about.sections[0]?.paragraphs[0]}>
      <HostedDemoNote />
      {copy.about.sections.map((block, index) => (
        <Prose
          key={block.id}
          block={index === 0 ? { ...block, paragraphs: block.paragraphs.slice(1) } : block}
        />
      ))}
      <Scorecard />
      {copy.about.afterScorecard.map((block) => (
        <Prose key={block.id} block={block} />
      ))}
      <Reveal as="section" className="mt-16">
        <h2 id="run" className="display m-0 text-[clamp(1.6rem,3vw,2.2rem)] text-ink">
          {copy.run.title}
        </h2>
        <p className="mt-4 mb-0 text-lg text-ink-2">{copy.run.intro}</p>
        <CommandBlock command={command} />
        <p className="mt-4 mb-0 text-sm text-ink-2">{copy.run.note}</p>
      </Reveal>
      <Prose
        block={{
          id: "independence",
          title: copy.about.independenceTitle,
          paragraphs: [t("public.independence")],
        }}
      />
      <Prose block={copy.about.who}>
        <p className="mt-8 mb-0">
          <a href={REPO_URL} className="btn btn-ghost" rel="noopener">
            {copy.about.sourceLink}{" "}
            <span className="arrow" aria-hidden="true">
              &rarr;
            </span>
          </a>
        </p>
      </Prose>
    </Frame>
  );
}

export function Privacy() {
  return (
    <Frame title={copy.privacy.title}>
      {copy.privacy.sections.map((block) => (
        <Prose key={block.title} block={block} />
      ))}
    </Frame>
  );
}

export function NotFound() {
  return (
    <Frame title={copy.notFound.title} lead={copy.notFound.body}>
      <p className="mt-8 mb-0">
        <a href="/" className="btn btn-primary">
          {copy.notFound.home}
        </a>
      </p>
    </Frame>
  );
}
