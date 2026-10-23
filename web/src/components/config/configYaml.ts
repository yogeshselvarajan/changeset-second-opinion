/*
 * The config endpoint returns JSON; the admin screen shows it as YAML, the form the community edits
 * it in. This is a small, deterministic writer for plain data (objects, arrays, strings, numbers,
 * booleans, null): keys keep the order they arrive in, and any string that could be misread is quoted.
 */

const PLAIN = /^[A-Za-z_][A-Za-z0-9_./-]*$/;
const RESERVED = /^(?:true|false|null|yes|no|on|off|~)$/i;

function scalar(value: string | number | boolean | null): string {
  if (value === null) return "null";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  return PLAIN.test(value) && !RESERVED.test(value) ? value : JSON.stringify(value);
}

function key(name: string): string {
  return PLAIN.test(name) && !RESERVED.test(name) ? name : JSON.stringify(name);
}

function isScalar(value: unknown): value is string | number | boolean | null {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function lines(value: unknown, pad: string): string[] {
  if (Array.isArray(value)) {
    if (value.length === 0) return [`${pad}[]`];
    return value.flatMap((item) => {
      if (isScalar(item)) return [`${pad}- ${scalar(item)}`];
      const inner = lines(item, `${pad}  `);
      if (inner.length === 1 && (inner[0] === `${pad}  []` || inner[0] === `${pad}  {}`)) {
        return [`${pad}- ${inner[0]?.trim()}`];
      }
      const [first, ...rest] = inner;
      return [`${pad}- ${(first ?? "").slice(pad.length + 2)}`, ...rest];
    });
  }
  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>).filter(
      ([, v]) => v !== undefined,
    );
    if (entries.length === 0) return [`${pad}{}`];
    return entries.flatMap(([name, item]) => {
      if (isScalar(item)) return [`${pad}${key(name)}: ${scalar(item)}`];
      const inner = lines(item, `${pad}  `);
      if (inner.length === 1 && (inner[0]?.trim() === "[]" || inner[0]?.trim() === "{}")) {
        return [`${pad}${key(name)}: ${inner[0]?.trim()}`];
      }
      return [`${pad}${key(name)}:`, ...inner];
    });
  }
  return [`${pad}${scalar(null)}`];
}

/**
 * A copy of `value` with every `banned_words` list replaced by a note that says how many entries
 * were left out. The words the drafts avoid are never printed on screen (the summary line shows
 * only a count), so the YAML view hides them the same way, at any depth.
 */
export function redactFlaggedWords(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(redactFlaggedWords);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([name, item]) => [
        name,
        name === "banned_words" && Array.isArray(item)
          ? `[${item.length} entries hidden]`
          : redactFlaggedWords(item),
      ]),
    );
  }
  return value;
}

/** The text of `value` as YAML, one line per array element. */
export function toYaml(value: unknown): string {
  return `${lines(value, "").join("\n")}\n`;
}
