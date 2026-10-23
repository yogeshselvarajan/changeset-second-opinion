import { MessageCircle, MessageSquare, Tag, Trash2, User } from "lucide-react";

import { withChangesetLink } from "../ChangesetLink";
import { copy } from "../copy";
import { Mark } from "../Mark";
import numbers from "../numbers.json";

/**
 * Five of the ten readings the Strands Decider 2B gave for one real changeset (Mumbai, saved in
 * backend/fixtures/demo, run on 20 October 2026). Probabilities are copied from that receipt; the
 * wording is the question each reading answers.
 */
export const DECIDER_SAMPLE = {
  changesetId: 189806470,
  readings: [
    { label: "An old or heavily edited feature was deleted", p: 0.7536 },
    { label: "The changeset comment matches the edits", p: 0.726 },
    { label: "There is enough evidence to judge", p: 0.6542 },
    { label: "New or changed tags follow ordinary OSM conventions", p: 0.3258 },
    { label: "The account is new or has very few changesets", p: 0.1043 },
  ],
} as const;

const EVIDENCE_ICONS = [MessageSquare, User, Trash2, Tag, MessageCircle] as const;

/** yes above 0.65, no below 0.35, otherwise the model says cannot tell (the panel's own cut points). */
function stateOf(p: number): "yes" | "no" | "unknown" {
  if (p > 0.65) return "yes";
  if (p < 0.35) return "no";
  return "unknown";
}

const STATE_WORD = { yes: "Yes", no: "No", unknown: "Cannot tell" } as const;

/**
 * Evidence in, ten readings out: the Decider drawn as a single clear step. Static markup first; the
 * bars grow once the block scrolls into view (CSS only, off for reduced motion).
 */
export function DeciderFlow() {
  const ms = String(Math.round(numbers.demo.median_model_ms));
  const [before = "", after = ""] = copy.decider.centerNote.split("{ms}");
  return (
    <div className="flow grid items-center gap-8 lg:grid-cols-[4fr_3fr_5fr] lg:gap-6">
      <div>
        <p className="eyebrow m-0 mb-4">{copy.decider.inLabel}</p>
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {copy.decider.inItems.map((item, index) => {
            const Icon = EVIDENCE_ICONS[index] ?? MessageSquare;
            return (
              <li
                key={item}
                className="flow-chip m-0 flex items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 text-ink"
              >
                <Icon aria-hidden="true" size={18} strokeWidth={1.75} className="text-accent" />
                {item}
              </li>
            );
          })}
        </ul>
      </div>

      <div className="flow-core mx-auto grid w-full max-w-[260px] place-items-center">
        <div className="flow-orb grid aspect-square w-full place-items-center rounded-full border border-line bg-surface-2 text-center">
          <div>
            <Mark className="mx-auto h-10 w-auto" />
            <p className="display mt-3 mb-0 text-xl text-ink">{copy.decider.centerName}</p>
            <p className="mt-1 mb-0 font-mono text-xs text-ink-2">
              {before}
              <span data-count={ms}>{ms}</span>
              {after}
            </p>
          </div>
        </div>
      </div>

      <div>
        <p className="eyebrow m-0 mb-4">{copy.decider.outLabel}</p>
        <div className="card p-5 md:p-6">
          <ul className="m-0 flex list-none flex-col gap-4 p-0">
            {DECIDER_SAMPLE.readings.map((reading) => {
              const state = stateOf(reading.p);
              return (
                <li key={reading.label} className="m-0">
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="text-ink">{reading.label}</span>
                    <span className="font-mono tabular-nums text-ink-2">
                      {reading.p.toFixed(2)} {STATE_WORD[state].toLowerCase()}
                    </span>
                  </div>
                  <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2">
                    <div
                      className="flow-bar h-full rounded-full"
                      data-state={state}
                      style={{ width: `${Math.round(reading.p * 100)}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="mt-5 mb-0 text-xs text-ink-2">
            {withChangesetLink(copy.decider.outNote, DECIDER_SAMPLE.changesetId)}
          </p>
        </div>
      </div>
    </div>
  );
}
