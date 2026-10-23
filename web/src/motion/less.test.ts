import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LESS_MOTION_EVENT, readLessMotion, restoreLessMotion, setLessMotion } from "./less";

/** The test environment's own localStorage is not a full one, so use a small stand-in. */
function stubStorage() {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
  });
  return store;
}

beforeEach(() => {
  stubStorage();
  delete document.documentElement.dataset.lessMotion;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the less motion switch", () => {
  it("is off until someone turns it on", () => {
    expect(readLessMotion()).toBe(false);
    expect(restoreLessMotion()).toBe(false);
    expect(document.documentElement.dataset.lessMotion).toBeUndefined();
  });

  it("turns on, tells the page, and is restored on the next visit", () => {
    const heard = vi.fn();
    window.addEventListener(LESS_MOTION_EVENT, heard);
    setLessMotion(true);
    expect(heard).toHaveBeenCalledTimes(1);
    expect(document.documentElement.dataset.lessMotion).toBe("true");
    delete document.documentElement.dataset.lessMotion;
    expect(restoreLessMotion()).toBe(true);
    expect(document.documentElement.dataset.lessMotion).toBe("true");
    setLessMotion(false);
    expect(readLessMotion()).toBe(false);
    expect(document.documentElement.dataset.lessMotion).toBeUndefined();
    window.removeEventListener(LESS_MOTION_EVENT, heard);
  });

  it("still works for this visit when the browser will not store anything", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    });
    expect(() => setLessMotion(true)).not.toThrow();
    expect(document.documentElement.dataset.lessMotion).toBe("true");
    expect(readLessMotion()).toBe(false);
  });
});
