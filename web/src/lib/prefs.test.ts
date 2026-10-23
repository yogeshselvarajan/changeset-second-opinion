import { describe, expect, it } from "vitest";

import {
  DENSITY_KEY,
  THEME_KEY,
  applyPrefs,
  readPrefs,
  writePrefs,
  type StorageLike,
} from "./prefs";

function memoryStorage(initial: Record<string, string> = {}): StorageLike & {
  data: Record<string, string>;
} {
  const data = { ...initial };
  return {
    data,
    getItem: (key) => data[key] ?? null,
    setItem: (key, value) => {
      data[key] = value;
    },
  };
}

describe("preferences", () => {
  it("defaults to system theme and comfortable density", () => {
    expect(readPrefs(memoryStorage())).toEqual({ theme: "system", density: "comfortable" });
  });

  it("round-trips through storage", () => {
    const storage = memoryStorage();
    writePrefs({ theme: "dark", density: "compact" }, storage);
    expect(storage.data[THEME_KEY]).toBe("dark");
    expect(storage.data[DENSITY_KEY]).toBe("compact");
    expect(readPrefs(storage)).toEqual({ theme: "dark", density: "compact" });
  });

  it("ignores unknown stored values", () => {
    const storage = memoryStorage({ [THEME_KEY]: "neon", [DENSITY_KEY]: "tiny" });
    expect(readPrefs(storage)).toEqual({ theme: "system", density: "comfortable" });
  });

  it("survives blocked storage", () => {
    const blocked: StorageLike = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readPrefs(blocked)).toEqual({ theme: "system", density: "comfortable" });
    expect(() => writePrefs({ theme: "light", density: "compact" }, blocked)).not.toThrow();
    expect(readPrefs(null).theme).toBe("system");
  });

  it("applies the choice on the root element, and system removes data-theme", () => {
    const root = document.documentElement;
    applyPrefs({ theme: "dark", density: "compact" }, root);
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(root.getAttribute("data-density")).toBe("compact");
    applyPrefs({ theme: "system", density: "comfortable" }, root);
    expect(root.hasAttribute("data-theme")).toBe(false);
    expect(root.getAttribute("data-density")).toBe("comfortable");
  });
});
