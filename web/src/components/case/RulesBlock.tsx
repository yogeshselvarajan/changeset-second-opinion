import { Info, OctagonX, TriangleAlert } from "lucide-react";

import type { RuleHit } from "../../api/types.gen";
import { t } from "../../i18n";
import { describeTrigger, ruleExplanation, severityMeta } from "./caseModel";
import { Section } from "./Section";
import { Untrusted } from "./Untrusted";

const SEVERITY_ICON = { info: Info, warn: TriangleAlert, block: OctagonX } as const;

/** A small icon per severity; the word beside it carries the meaning, the icon only aids scanning. */
function SeverityIcon({ severity }: { severity: RuleHit["severity"] }) {
  const Icon = SEVERITY_ICON[severity];
  return <Icon size={12} strokeWidth={2} />;
}

/**
 * The rules that fired, from parsed evidence (counts, ages, coverage), never from a model answer.
 * Each shows its severity as a glyph and a word, what it means, and what triggered it.
 */
export function RulesBlock({
  rules,
  reveal = false,
}: {
  rules: readonly RuleHit[];
  reveal?: boolean;
}) {
  return (
    <Section id="rules" title={t("case.rules.title")} testId="rules">
      {rules.length === 0 ? (
        <p className="text-sm text-text-muted" data-testid="no-rules">
          {t("case.rules.none")}
        </p>
      ) : (
        <ul className={`space-y-3 ${reveal ? "cso-pop" : ""}`} data-testid="rules-list">
          {rules.map((rule) => {
            const severity = severityMeta(rule.severity);
            const explanation = ruleExplanation(rule.code);
            const trigger = describeTrigger(rule.triggered_by);
            return (
              <li
                key={rule.code}
                className="rounded border border-border p-2"
                data-rule={rule.code}
                data-severity={rule.severity}
              >
                <p className="text-sm font-semibold">
                  <span
                    aria-hidden="true"
                    data-glyph={severity.glyph}
                    className="mr-2 inline-grid size-5 place-items-center rounded-[var(--radius-control)] border border-control-border align-text-bottom"
                  >
                    <SeverityIcon severity={rule.severity} />
                  </span>
                  {rule.code} · <Untrusted value={rule.label} />
                  <span className="ml-2 text-xs font-normal text-text-muted">
                    {t(severity.label)}
                  </span>
                </p>
                {explanation ? <p className="mt-1 text-sm">{explanation}</p> : null}
                {trigger.length > 0 ? (
                  <dl
                    aria-label={t("case.rules.triggeredBy")}
                    className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-xs"
                  >
                    {trigger.map((item) => (
                      <div key={item.name} className="contents">
                        <dt className="font-mono text-text-muted">{item.name}</dt>
                        <dd className="font-mono">
                          <Untrusted value={item.value} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}
