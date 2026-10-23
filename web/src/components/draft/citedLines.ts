const ID = /^[A-Z]\d{1,4}$/;
const MAX_LINE = 240;

export interface CitedLine {
  id: string;
  /** The evidence text for that id, as the model saw it (untrusted: render as plain text). */
  line: string;
}

/**
 * The lines of the evidence text that a draft cites. Each line of that text starts with its id
 * ("E3 way/123 ..."), so a cited id is looked up by prefix and nothing else is read. An id with no
 * matching line is left out, a malformed id is ignored, and a long line is cut.
 */
export function citedEvidenceLines(
  renderedText: string | undefined,
  ids: readonly string[] | undefined,
): CitedLine[] {
  if (!renderedText || !ids || ids.length === 0) return [];
  const lines = renderedText.split(/\r?\n/);
  const out: CitedLine[] = [];
  for (const id of new Set(ids)) {
    if (!ID.test(id)) continue;
    const found = lines.find((line) => line.startsWith(`${id} `));
    if (found === undefined) continue;
    out.push({ id, line: found.length > MAX_LINE ? `${found.slice(0, MAX_LINE)}...` : found });
  }
  return out;
}
