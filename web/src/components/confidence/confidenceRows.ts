import { humanize } from "../case/caseModel";
import type { ConfidenceRow } from "./ConfidenceBlock";

export interface OptionLabel {
  label: string;
  description?: string;
}

/**
 * Turn the API's `{code: probability}` map into rows. Options come first in the option set's order
 * (the order the model was asked in), then any other code the API sent, in the API's own order, so
 * nothing the backend reported is dropped.
 */
export function confidenceRows(
  probabilities: Readonly<Record<string, number | undefined>> | null | undefined,
  lookup: ReadonlyMap<string, OptionLabel>,
  order: readonly string[] = [],
): ConfidenceRow[] {
  const entries: [string, number][] = [];
  for (const [code, value] of Object.entries(probabilities ?? {})) {
    if (typeof value === "number") entries.push([code, value]);
  }
  const byCode = new Map(entries);
  const rows: ConfidenceRow[] = [];
  const seen = new Set<string>();
  const push = (code: string, probability: number) => {
    const info = lookup.get(code);
    rows.push({
      code,
      label: info?.label ?? humanize(code),
      description: info?.description,
      probability,
    });
    seen.add(code);
  };
  for (const code of order) {
    const probability = byCode.get(code);
    if (probability !== undefined) push(code, probability);
  }
  for (const [code, probability] of entries) {
    if (!seen.has(code)) push(code, probability);
  }
  return rows;
}
