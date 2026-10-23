import en from "./messages/en.json";

/** Every key in the one shipped catalogue; a typo in a key is a compile error. */
export type MessageKey = keyof typeof en;

const catalogue: Record<string, string> = en;

/** Look up a message and fill `{name}` placeholders. Unknown keys fall back to the key itself. */
export function t(key: MessageKey, params?: Record<string, string | number>): string {
  const template = catalogue[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name];
    return value === undefined ? match : String(value);
  });
}
