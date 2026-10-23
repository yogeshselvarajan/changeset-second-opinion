import { afterEach, describe, expect, it, vi } from "vitest";

import { neighbour, queuePosition, readQueueContext, saveQueueContext } from "./queueContext";

afterEach(() => {
  window.sessionStorage.clear();
  vi.restoreAllMocks();
});

describe("queue context", () => {
  it("round-trips the ids of the current list in order", () => {
    saveQueueContext(["a", "b", "c"]);
    expect(readQueueContext()).toEqual(["a", "b", "c"]);
  });

  it("is empty when nothing was saved, or when the saved value is not a list of ids", () => {
    expect(readQueueContext()).toEqual([]);
    window.sessionStorage.setItem("cso.queue.context", "{not json");
    expect(readQueueContext()).toEqual([]);
    window.sessionStorage.setItem("cso.queue.context", JSON.stringify({ a: 1 }));
    expect(readQueueContext()).toEqual([]);
    window.sessionStorage.setItem("cso.queue.context", JSON.stringify(["a", 3, null, "b"]));
    expect(readQueueContext()).toEqual(["a", "b"]);
  });

  it("finds the position of a case and its neighbours", () => {
    const ids = ["a", "b", "c"];
    expect(queuePosition(ids, "b")).toEqual({ index: 1, total: 3 });
    expect(queuePosition(ids, "z")).toBeNull();
    expect(neighbour(ids, "b", 1)).toEqual({ id: "c", position: 3, total: 3 });
    expect(neighbour(ids, "b", -1)).toEqual({ id: "a", position: 1, total: 3 });
  });

  it("has no neighbour past either end or for a case outside the list", () => {
    const ids = ["a", "b", "c"];
    expect(neighbour(ids, "a", -1)).toBeNull();
    expect(neighbour(ids, "c", 1)).toBeNull();
    expect(neighbour(ids, "z", 1)).toBeNull();
    expect(neighbour([], "a", 1)).toBeNull();
  });

  it("does not throw when storage is blocked", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    const original = Object.getOwnPropertyDescriptor(window, "sessionStorage");
    Object.defineProperty(window, "sessionStorage", { configurable: true, value: blocked });
    try {
      expect(() => saveQueueContext(["a"])).not.toThrow();
      expect(readQueueContext()).toEqual([]);
    } finally {
      if (original) Object.defineProperty(window, "sessionStorage", original);
    }
  });
});
