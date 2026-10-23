/** One run of a word-level comparison: unchanged text, text only in the new version, or only in the old. */
export interface DiffRun {
  kind: "same" | "ins" | "del";
  text: string;
}

/** Past this many pieces on either side the comparison would be slow, so it reports a plain replace. */
const MAX_PIECES = 600;

function pieces(text: string): string[] {
  return text.split(/(\s+)/).filter((piece) => piece !== "");
}

function merge(runs: DiffRun[]): DiffRun[] {
  const out: DiffRun[] = [];
  for (const run of runs) {
    const last = out[out.length - 1];
    if (last && last.kind === run.kind) last.text += run.text;
    else out.push({ ...run });
  }
  return out;
}

/**
 * Compare two texts word by word (whitespace counts as a piece so the runs read back as the text).
 * Concatenating the `same` and `ins` runs gives `after`; the `same` and `del` runs give `before`.
 */
export function wordDiff(before: string, after: string): DiffRun[] {
  if (before === after) return before === "" ? [] : [{ kind: "same", text: before }];
  const a = pieces(before);
  const b = pieces(after);
  if (a.length > MAX_PIECES || b.length > MAX_PIECES) {
    return merge([
      ...(before ? [{ kind: "del" as const, text: before }] : []),
      ...(after ? [{ kind: "ins" as const, text: after }] : []),
    ]);
  }
  // Longest common subsequence table, filled from the end so the walk below runs forward.
  const table: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      const row = table[i] as number[];
      const next = table[i + 1] as number[];
      row[j] =
        a[i] === b[j]
          ? (next[j + 1] as number) + 1
          : Math.max(next[j] as number, row[j + 1] as number);
    }
  }
  const runs: DiffRun[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      runs.push({ kind: "same", text: a[i] as string });
      i += 1;
      j += 1;
    } else if (
      ((table[i + 1] as number[])[j] as number) >= ((table[i] as number[])[j + 1] as number)
    ) {
      runs.push({ kind: "del", text: a[i] as string });
      i += 1;
    } else {
      runs.push({ kind: "ins", text: b[j] as string });
      j += 1;
    }
  }
  while (i < a.length) runs.push({ kind: "del", text: a[i++] as string });
  while (j < b.length) runs.push({ kind: "ins", text: b[j++] as string });
  return merge(runs);
}

/** True when the diff holds any change. */
export function hasChanges(runs: readonly DiffRun[]): boolean {
  return runs.some((run) => run.kind !== "same");
}
